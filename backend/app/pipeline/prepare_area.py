"""S1.12: fetch, align and cache every static layer for one AOI. Idempotent: groups already in GCS are skipped."""
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import osmnx as ox
from rasterio.features import rasterize
from rasterio.transform import Affine
from scipy.ndimage import binary_dilation, distance_transform_edt

from app.config import get_settings
from app.engines import buildings as bld, crowding, fsi as fsi_engine, hydrology as hy, landslide as ls, population, rainfall
from app.engines import drains as drn, pluvial, roads, shelters as shel
from app.engines.grid import lonlat_bounds, lonlat_to_rowcol, make_grid, rowcol_to_lonlat, terrain, terrain_coarse, xy_to_rowcol
from app.engines.render import to_png, to_png_classes
from scipy.spatial import cKDTree
from app.models.aoi import AOI
from app.models.grid import GridSpec
from app.services import earth_engine as ees
from app.services import firestore as fs
from app.services import osm, storage

log = logging.getLogger(__name__)

EE_GROUPS = ["terrain", "hydro30", "landcover", "hazard_hist", "population"]
VECTOR_FILES = ["buildings.parquet", "G_walk.graphml", "G_drive.graphml", "pois.parquet", "waterways.parquet"]


def _distance_m(mask: np.ndarray, cell: float) -> np.ndarray:
    if not mask.any():
        return np.full(mask.shape, np.nan, np.float32)
    return (distance_transform_edt(~mask) * cell).astype(np.float32)


def _ee_group(aoi_id: str, grid: GridSpec, images: dict, group: str, warnings: list[str], meta: dict) -> None:
    arrays = ees.fetch_grid(images[group], grid, ees.GROUP_BANDS[group])
    if group == "terrain":
        arrays.update(terrain(arrays["dem"], grid.cell))
    elif group == "hydro30":
        stream = np.nan_to_num(arrays["upa"]) >= get_settings().stream_upa_km2
        arrays["stream"] = stream
        arrays["dist_stream_m"] = _distance_m(stream, grid.cell)
        if not stream.any():
            warnings.append("No stream cells above the drainage-area threshold in this area")
    elif group == "population":
        pop30 = np.nan_to_num(arrays.pop("pop_density")) * grid.cell**2
        raw, total = float(pop30.sum()), ees.worldpop_total(grid)
        if raw > 0:
            pop30 *= total / raw
        else:
            warnings.append("No WorldPop population in this area")
        log.info("population: raw grid sum %.0f, EE total %.0f, rescaled sum %.0f", raw, total, pop30.sum())
        meta.update(pop_raw_sum=raw, pop_ee_total=total, pop30_sum=float(pop30.sum()))
        arrays["pop30"] = pop30.astype(np.float32)
    storage.save_layers(aoi_id, group, arrays, grid)


def _buildings(aoi: AOI, grid: GridSpec, warnings: list[str]) -> None:
    gdf, w = ees.fetch_buildings(aoi.bbox, grid)
    if len(gdf) == 0:  # Open Buildings covers the Global South only: fall back to OpenStreetMap footprints
        try:
            gdf = osm.buildings(tuple(aoi.bbox), grid.crs)
            w = [f"Google Open Buildings has no coverage here; using {len(gdf):,} OpenStreetMap building footprints"
                 " (heights from OSM tags where mapped)"] if len(gdf) else w + ["No OpenStreetMap buildings either"]
        except Exception as e:
            w = w + [f"OpenStreetMap buildings unavailable: {e.__class__.__name__}"]
    warnings.extend(w)
    storage.save_gdf(aoi.aoi_id, "buildings.parquet", gdf)


def _osm(aoi_id: str, grid: GridSpec, warnings: list[str]) -> None:
    """OpenStreetMap roads (walk and drive), road bridges, places and waterways. One Overpass request for all of them
    (osm.bundle, 17 Oct: ~40 s for Dera Ghazi Khan, results identical to the five separate requests that took 2-6 min);
    if that fails, the separate requests one after another (in parallel they were refused by the busy public server)."""
    bb = lonlat_bounds(grid)
    files = {"drive": "G_drive.graphml", "walk": "G_walk.graphml", "bridges": "bridge_ways.parquet",
             "pois": "pois.parquet", "waterways": "waterways.parquet"}
    missing = [k for k, f in files.items() if not storage.exists(aoi_id, f)]
    if not missing:
        return
    try:
        b = osm.bundle(bb)
        for k in missing:
            (storage.save_graph if k in ("drive", "walk") else storage.save_gdf)(aoi_id, files[k], b[k])
        return
    except Exception as e:
        log.warning("OSM bundle failed (%s); trying the separate requests", e)
    for kind in ("walk", "drive"):
        if kind in missing:
            try:
                storage.save_graph(aoi_id, files[kind], osm.graph(bb, kind))
            except Exception as e:
                warnings.append(f"OSM {kind} network unavailable: {e}")
    if "bridges" in missing:
        try:
            storage.save_gdf(aoi_id, files["bridges"], osm.bridge_ways(bb))
        except Exception as e:
            warnings.append(f"OSM bridges unavailable: {e}")
    if "pois" in missing or "waterways" in missing:
        try:
            pois, water = osm.pois_and_waterways(bb)
            storage.save_gdf(aoi_id, files["pois"], pois)
            storage.save_gdf(aoi_id, files["waterways"], water)
        except Exception as e:
            warnings.append(f"OSM POIs/waterways unavailable: {e}")


def _derived(aoi_id: str, grid: GridSpec, warnings: list[str]) -> None:
    road = np.zeros((grid.height, grid.width), bool)
    if storage.exists(aoi_id, "G_drive.graphml"):
        edges = ox.graph_to_gdfs(storage.load_graph(aoi_id, "G_drive.graphml"), nodes=False).to_crs(grid.crs)
        transform = Affine(grid.cell, 0, grid.x0, 0, -grid.cell, grid.y0)
        road = rasterize(((g, 1) for g in edges.geometry), out_shape=road.shape, transform=transform,
                         all_touched=True, dtype="uint8").astype(bool)
    if not road.any():
        warnings.append("No OSM drivable roads in this area; dist_road_m is empty")
    storage.save_layers(aoi_id, "derived", {"dist_road_m": _distance_m(road, grid.cell)}, grid)


def src_name(n: float) -> str:
    return f"src_n{n:.3f}.json"


def _hydrology(aoi_id: str, grid: GridSpec, warnings: list[str], meta: dict) -> None:
    """S2: native-grid D8 hydrology, reaches, SRC tables, hotspots; mapped to the 30 m grid (S2.12)."""
    cfg = get_settings()
    hg = hy.make_hydro_grid(lonlat_bounds(grid))
    m = ees.fetch_merit_native(hg)
    down = hy.downstream_index(m["d8"])
    a_loc = hy.local_accumulation_km2(down, hg.cell_area)
    stream = np.nan_to_num(m["upa"]) >= cfg.stream_upa_km2
    drain = hy.drain_cells(stream, down)
    reach_flat, reaches = hy.build_reaches(hg, stream, down, m["elv"], m["upa"], a_loc)
    catch = np.where(drain >= 0, reach_flat[np.maximum(drain, 0)], -1).astype(np.int32)
    slope = hy.local_slope(m["elv"], hg)
    src = hy.src_tables(m["hnd"], catch, slope, reaches, hg.cell_area, cfg.manning_n)
    hs = hy.hotspots(hg, stream, down, m["upa"])

    rows, cols = np.indices((grid.height, grid.width))
    lon, lat = rowcol_to_lonlat(grid, rows.ravel(), cols.ravel())
    hidx = hy.hydro_index_for_lonlat(hg, np.asarray(lon), np.asarray(lat))
    inside = hidx >= 0
    safe = np.maximum(hidx, 0)
    shape = (grid.height, grid.width)
    h30 = storage.load_layers(aoi_id, "hydro30")
    h30["reach_id"] = np.where(inside, catch[safe], -1).astype(np.int32).reshape(shape)
    h30["drain_cell"] = np.where(inside, drain[safe], -1).astype(np.int32).reshape(shape)
    storage.save_layers(aoi_id, "hydro30", h30, grid)

    storage.save_layers(aoi_id, "hydro_native", {
        "hnd": m["hnd"], "elv": m["elv"], "upa": m["upa"], "d8": m["d8"], "downstream": down.astype(np.int32),
        "a_local_km2": a_loc.astype(np.float32), "stream": stream, "drain_cell": drain.astype(np.int32),
        "catch_reach": catch, "slope": slope.astype(np.float32)}, grid)
    storage.put_json(aoi_id, "hydro_grid.json", hg.to_dict())
    storage.put_json(aoi_id, "reaches.json", reaches)
    storage.put_json(aoi_id, src_name(cfg.manning_n), src)
    storage.put_json(aoi_id, "hotspots.json", hs)

    stream30 = np.where(inside, stream.ravel()[safe], False).reshape(shape)
    storage.save_png(aoi_id, "streams", to_png(np.where(stream30, 1.0, np.nan), "blues", 0, 1, alpha=230))
    if len(reaches) == 0:
        warnings.append("No stream reaches found; flood modelling unavailable for this area")
    meta.update(n_reaches=len(reaches), max_A_up_km2=round(max((r["A_up_km2"] for r in reaches), default=0), 1),
                hydro_grid=f"{hg.width}x{hg.height}")


def _fsi(aoi_id: str, meta: dict) -> None:
    """S4: static flood susceptibility (AHP), saved in the `susceptibility` group."""
    t, h, lc, hz = (storage.load_layers(aoi_id, g) for g in ("terrain", "hydro30", "landcover", "hazard_hist"))
    scores = fsi_engine.factor_scores(
        hand=h["hand"], gfd_count=hz["gfd_count"], gsw_occ=hz["gsw_occ"], dist_stream_m=h["dist_stream_m"],
        upa=h["upa"], rain_clim=hz["rain_clim"], slope_deg=t["slope_deg"],
        C=rainfall.runoff_c(lc["lc_class"], get_settings().runoff_c))
    val, cls, info = fsi_engine.fsi(scores, get_settings().fsi_ahp_matrix)
    grid = storage.load_grid(aoi_id)
    sus = storage.load_layers(aoi_id, "susceptibility") if storage.exists(aoi_id, "susceptibility.npz") else {}
    storage.save_layers(aoi_id, "susceptibility", {**sus, "fsi": val, "fsi_class": cls}, grid)
    storage.save_png(aoi_id, "fsi", to_png_classes(cls))
    meta["fsi"] = info


def _lsi(aoi: AOI, grid: GridSpec, warnings: list[str], meta: dict) -> None:
    """S5 static: FR ratings learned on a 90 m grid over the AOI + 50 km, AHP weights, training-region scaling."""
    cfg = get_settings()
    tg = make_grid(aoi.bbox, buffer_m=50_000, cell=90, snap=90)
    T = ees.fetch_training_layers(tg, bare_earth=_bare(aoi))
    t_terr = terrain(T["dem"], tg.cell)
    t_stream = np.nan_to_num(T["upa"]) >= cfg.stream_upa_km2
    pts = ees.fetch_landslides(tg, cfg.landslide_max_accuracy_km)
    slides = np.zeros((tg.height, tg.width), bool)
    n_in = 0
    if pts:
        r, c = lonlat_to_rowcol(tg, [p[0] for p in pts], [p[1] for p in pts])
        ok = (r >= 0) & (r < tg.height) & (c >= 0) & (c < tg.width)
        slides[r[ok], c[ok]] = True
        slides = binary_dilation(slides)  # 1-cell buffer
        n_in = int(ok.sum())
    rain_edges = ls.rain_quintile_edges(T["rain_clim"])
    # Training-box roads come from GRIP4 (global, major roads); the AOI uses OSM drivable roads. Before 17 Oct the
    # training road factor was a constant mean rating, which mis-calibrated the AOI near roads.
    t_layers = {**t_terr, "ndvi": T["ndvi"], "soil_clay": T["soil_clay"], "rain_clim": T["rain_clim"],
                "dist_stream_m": _distance_m(t_stream, tg.cell), "dist_road_m": T["dist_road_m"]}
    t_cls = ls.classify(t_layers, rain_edges)
    ratings, n = ls.learn_ratings(t_cls, slides, ls.LSI_FACTORS, n_points=n_in)
    method = "frequency_ratio" if n >= ls.MIN_SLIDES else "expert"
    if method == "expert":
        warnings.append(f"Only {n} landslide records located to within {cfg.landslide_max_accuracy_km:g} km near this "
                        f"area (< {ls.MIN_SLIDES}); expert ratings used")
    train_raw, _ = ls.lsi_raw(t_cls, ratings, cfg.lsi_ahp_matrix)
    # Validation: ROC AUC of the training-region score against the landslide cells. With expert ratings this is an
    # independent check; with FR it is a success rate (fitted on the same points), so it is reported as such.
    auc = ls.auc(train_raw, slides)

    t, h, lc, hz, dv = (storage.load_layers(aoi.aoi_id, g) for g in ("terrain", "hydro30", "landcover", "hazard_hist", "derived"))
    tc = terrain_coarse(t["dem"], grid.cell, factor=round(tg.cell / grid.cell))  # match the 90 m training scale
    a_layers = {"slope_deg": tc["slope_deg"], "aspect_deg": tc["aspect_deg"], "curv": tc["curv"], "ndvi": lc["ndvi"],
                "soil_clay": lc["soil_clay"], "rain_clim": hz["rain_clim"], "dist_stream_m": h["dist_stream_m"],
                "dist_road_m": dv["dist_road_m"]}
    a_cls = ls.classify(a_layers, rain_edges)
    raw, info = ls.lsi_raw(a_cls, ratings, cfg.lsi_ahp_matrix)
    val, cls, edges = ls.normalise_and_classify(raw, train_raw, t["slope_deg"])
    # Road closures use the same index with the distance-to-road factor neutral (its mean rating): road cuts do raise
    # susceptibility, but judging a road closed because it is a road is circular (road cells were 6.5x more often in
    # class 5 than other ground in Rudraprayag, 16 Oct).
    neutral = lambda c: {**c, "road": np.full_like(c["road"], -1)}  # noqa: E731
    train_nr, _ = ls.lsi_raw(neutral(t_cls), ratings, cfg.lsi_ahp_matrix)
    raw_nr, _ = ls.lsi_raw(neutral(a_cls), ratings, cfg.lsi_ahp_matrix)
    val_nr, _, edges_nr = ls.normalise_and_classify(raw_nr, train_nr, t["slope_deg"])
    sus = storage.load_layers(aoi.aoi_id, "susceptibility") if storage.exists(aoi.aoi_id, "susceptibility.npz") else {}
    storage.save_layers(aoi.aoi_id, "susceptibility", {**sus, "lsi_static": val, "lsi_class": cls,
                                                       "lsi_edges": np.asarray(edges, np.float32),
                                                       "lsi_static_noroad": val_nr, "lsi_edges_noroad": np.asarray(edges_nr, np.float32)}, grid)
    storage.save_png(aoi.aoi_id, "lsi_static", to_png_classes(cls))
    meta["lsi"] = {**info, "method": method, "landslide_records": n, "ratings": ratings,
                   "auc": None if auc is None else round(auc, 3),
                   "auc_kind": "success rate (fitted points)" if method == "frequency_ratio" else "validation (independent points)",
                   "road_source_training": "GRIP4 (Meijer et al. 2018)",
                   "class_edges": [round(e, 4) for e in edges], "training_grid": f"{tg.width}x{tg.height} @ 90 m"}


def _building_proxy(aoi_id: str, grid: GridSpec, meta: dict) -> None:
    """S6.1-S6.4 static part: proxy structure class per building and base population per building."""
    b = storage.load_gdf(aoi_id, "buildings.parquet")
    cen = b.geometry.centroid
    x, y = cen.x.to_numpy(), cen.y.to_numpy()
    rows, cols = xy_to_rowcol(grid, x, y)
    area, height = b["area_m2"].to_numpy(float), b["height_m"].to_numpy(float)
    cluster = bld.cluster_flags(x, y, area)
    cls, F, conf, floors = bld.classify(area, height, b["presence_2016"].to_numpy(float),
                                        b["presence_2023"].to_numpy(float), cluster)
    source = bld.apply_field_overrides(b["bid"].tolist(), cls, F, conf, {})  # S12 photo results plug in here
    pop = storage.load_layers(aoi_id, "population")
    pop_b, unattr = population.distribute(pop["pop30"], rows, cols, area, height, block=3)
    ll = cen.to_crs("EPSG:4326")
    b = b.assign(lon=ll.x.to_numpy(), lat=ll.y.to_numpy(), row=rows, col=cols, structure_class=cls.astype(str),
                 fragility=F, confidence=conf, floors=floors, source=source.astype(str), pop_base=pop_b)
    storage.save_gdf(aoi_id, "buildings_proxy.parquet", b)
    storage.save_layers(aoi_id, "population", {**pop, "pop_unattributed": unattr.astype(np.float32)}, grid)
    meta["buildings"] = {"count": int(len(b)), "by_class": b["structure_class"].value_counts().to_dict(),
                         "pop_in_buildings": round(float(pop_b.sum())), "pop_unattributed": round(float(unattr.sum()))}


def _network(aoi: AOI, grid: GridSpec, warnings: list[str], meta: dict) -> None:
    """S7.1-S7.6 + S9: routable edge tables, crowding grid and edge crowding, shelters and medical facilities."""
    aoi_id = aoi.aoi_id
    t = storage.load_layers(aoi_id, "terrain")
    sus = storage.load_layers(aoi_id, "susceptibility")
    lsi_class = sus.get("lsi_class")
    hand = storage.load_layers(aoi_id, "hydro30")["hand"]
    b = storage.load_gdf(aoi_id, "buildings_proxy.parquet")
    pois = storage.load_gdf(aoi_id, "pois.parquet").to_crs(grid.crs)

    tables = {}
    for mode in ("walk", "drive"):
        name = f"G_{mode}.graphml"
        if not storage.exists(aoi_id, name):
            warnings.append(f"No OSM {mode} network; {mode} routing unavailable")
            continue
        G = storage.load_graph(aoi_id, name)
        if mode == "drive":
            G = ox.add_edge_travel_times(ox.add_edge_speeds(G))
        tables[mode] = roads.edge_table(ox.project_graph(G, to_crs=grid.crs), grid, mode, t["dem"], t["slope_deg"], lsi_class)

    # S9 crowding grid from POI attractors + building density
    poi_rc, attractors = [], []
    for _, p in pois.iterrows():
        w, label = crowding.poi_weight(p.to_dict())
        if w > 0:
            r, c = xy_to_rowcol(grid, p.geometry.centroid.x, p.geometry.centroid.y)
            poi_rc.append((int(r), int(c), w))
            attractors.append((p.geometry.centroid.x, p.geometry.centroid.y, label, shel.clean(p.get("name"))))
    crowd, raw = crowding.crowd_grid((grid.height, grid.width), poi_rc, b["row"], b["col"], grid.cell, return_raw=True)
    raw_max = float(raw.max()) or 1.0
    sus_c = {"crowd": crowd}
    storage.save_layers(aoi_id, "crowding", sus_c, grid)
    storage.save_png(aoi_id, "crowd", to_png(np.where(crowd > 0.05, crowd, np.nan), "risk", 0, 1))
    order = np.argsort(-raw.ravel())
    hot: list[dict] = []
    for f in order[:5000]:
        r, c = divmod(int(f), grid.width)
        x, y = grid.x0 + (c + 0.5) * grid.cell, grid.y0 - (r + 0.5) * grid.cell
        if any(math.hypot(x - h["x"], y - h["y"]) < 300 for h in hot):
            continue
        near = [a for a in attractors if math.hypot(a[0] - x, a[1] - y) < 300]
        lon, lat = rowcol_to_lonlat(grid, r, c)
        hot.append({"id": f"X{len(hot) + 1}", "x": x, "y": y, "lon": round(float(lon), 6), "lat": round(float(lat), 6),
                    "score": round(float(raw[r, c]) / raw_max, 3),
                    "top_attractors": sorted({f"{a[2]}{': ' + a[3] if a[3] else ''}" for a in near})[:3]})
        if len(hot) >= 10:
            break
    storage.put_json(aoi_id, "crowd_hotspots.json", [{k: v for k, v in h.items() if k not in ("x", "y")} for h in hot])

    for mode, (edges, nodes) in tables.items():
        edges["crowd_e"] = [crowding.edge_crowd(crowd, cells, n) for cells, n in zip(edges["cells"], edges["narrowness"])]
        storage.save_gdf(aoi_id, f"edges_{mode}.parquet", edges)
        storage.save_gdf(aoi_id, f"nodes_{mode}.parquet", nodes)

    # S7.5-S7.6 shelters and medical
    w, s, e, n = aoi.bbox
    in_aoi = lambda d: ((d["lon"] >= w) & (d["lon"] <= e) & (d["lat"] >= s) & (d["lat"] <= n)).to_numpy()  # noqa: E731
    sh, med = shel.from_pois(pois, b)
    n_osm = len(sh)
    n_proper = sum(1 for x in sh if x["kind"] != shel.WORSHIP)  # halls of worship need confirmation
    if n_proper < shel.MIN_OSM_SHELTERS:
        warnings.append(f"Only {n_proper} schools/community halls in OpenStreetMap here ({n_osm - n_proper} places of "
                        "worship); added unverified large-building candidates. Add or confirm shelters with local authorities.")
        sh += shel.candidate_large_buildings(b, hand, lsi_class, in_aoi, shel.MAX_CANDIDATES - n_proper)
    trees = {m: (cKDTree(nodes[["x", "y"]].to_numpy()), nodes["node"].to_numpy()) for m, (_, nodes) in tables.items()}
    out = []
    for prefix, lst in (("S", sh), ("M", med)):
        recs = []
        for i, rec in enumerate(lst, start=1):
            r, c = xy_to_rowcol(grid, rec["x"], rec["y"])
            r, c = int(np.clip(r, 0, grid.height - 1)), int(np.clip(c, 0, grid.width - 1))
            lon, lat = rowcol_to_lonlat(grid, r, c)
            nodes_ = {f"node_{m}": int(ids[tr.query([rec["x"], rec["y"]])[1]]) for m, (tr, ids) in trees.items()}
            recs.append({**rec, "id": f"{prefix}{i}", "lon": round(float(lon), 6), "lat": round(float(lat), 6),
                         "row": r, "col": c, "hand_m": round(float(hand[r, c]), 1),
                         "lsi_class": int(lsi_class[r, c]) if lsi_class is not None else 0,
                         "primary": bool(w <= lon <= e and s <= lat <= n), **nodes_})
        out.append(recs)
    storage.put_json(aoi_id, "shelters.json", out[0])
    storage.put_json(aoi_id, "medical.json", out[1])
    meta["network"] = {m: {"nodes": int(len(nd)), "edges": int(len(ed)), "bridges": int(ed["bridge"].sum())}
                       for m, (ed, nd) in tables.items()}
    meta["bridges"] = build_bridges(aoi_id, grid, warnings)
    meta["shelters"] = {"osm": n_osm, "total": len(out[0]), "medical": len(out[1])}


def build_bridges(aoi_id: str, grid: GridSpec, warnings: list[str]) -> dict:
    """Real bridge spans with deck heights and their links to the routable edges (engines/bridges.py) -> bridges.json."""
    from app.engines import bridges as brg
    if not storage.exists(aoi_id, "bridge_ways.parquet"):
        try:
            storage.save_gdf(aoi_id, "bridge_ways.parquet", osm.bridge_ways(lonlat_bounds(grid)))
        except Exception as e:
            warnings.append(f"OSM bridges unavailable: {e}")
            return {"spans": 0}
    ways = storage.load_gdf(aoi_id, "bridge_ways.parquet")
    h30 = storage.load_layers(aoi_id, "hydro30")
    water = storage.load_gdf(aoi_id, "waterways.parquet").to_crs(grid.crs) if storage.exists(aoi_id, "waterways.parquet") else None
    water_lines = [g for g in water.geometry if g is not None and g.geom_type in ("LineString", "MultiLineString")] if water is not None else None
    spans = brg.spans(ways.to_crs(grid.crs) if len(ways) else None, grid, h30["hand"], h30["reach_id"],
                      h30.get("dist_stream_m"), water_lines)
    links = {}
    for m in ("walk", "drive"):
        if storage.exists(aoi_id, f"edges_{m}.parquet"):
            edges = storage.load_gdf(aoi_id, f"edges_{m}.parquet").reset_index(drop=True)
            links[m] = {str(e): ks for e, ks in brg.link_edges(spans, edges.geometry).items()}
    out = []
    for s in spans:
        r, c = xy_to_rowcol(grid, s["x"], s["y"])
        lon, lat = rowcol_to_lonlat(grid, int(np.clip(r, 0, grid.height - 1)), int(np.clip(c, 0, grid.width - 1)))
        line = gpd.GeoSeries([s["geometry"]], crs=grid.crs).to_crs("EPSG:4326").iloc[0]
        out.append({k: v for k, v in s.items() if k not in ("geometry", "x", "y")} |
                   {"lon": round(float(lon), 6), "lat": round(float(lat), 6), "line": [[round(x, 6), round(y, 6)] for x, y in line.coords]})
    storage.put_json(aoi_id, "bridges.json", {"spans": out, "links": links})
    return {"spans": len(out), "over_river": sum(1 for s in out if s["reach"] >= 0),
            "not_open": sum(1 for s in out if s["status"] != "open"),
            "deck_at_minimum": sum(1 for s in out if s["deck_source"] == "minimum")}


def _bare(aoi: AOI) -> bool:
    """Bare-earth terrain (FABDEM) for every new area: the surface model's building tops make false slopes (landslides
    at building edges) and false dams for water. Areas prepared as "river" before 17 Oct keep Copernicus GLO-30 so
    their cached layers stay consistent."""
    return aoi.mode != "river"


def _urban(aoi: AOI, grid: GridSpec, warnings: list[str], meta: dict) -> None:
    """S13 static part (urban mode): depression analysis on the filled DEM and drain/culvert candidates."""
    aoi_id = aoi.aoi_id
    try:
        dem = ees.fetch_fabdem(grid)
        dem_src = "FABDEM (bare earth)"
    except Exception as e:  # fall back to the surface model, with a warning
        dem = storage.load_layers(aoi_id, "terrain")["dem"]
        dem_src = "Copernicus GLO-30 (surface model)"
        warnings.append(f"Bare-earth DEM unavailable ({e.__class__.__name__}); ponding uses the surface model, which includes buildings")
    C = rainfall.runoff_c(storage.load_layers(aoi_id, "landcover")["lc_class"], get_settings().runoff_c)
    st = pluvial.prepare(dem, grid.cell, C)
    st["dem_bare"] = dem.astype(np.float32)
    storage.save_layers(aoi_id, "pluvial", st, grid)
    water = storage.load_gdf(aoi_id, "waterways.parquet").to_crs(grid.crs) if storage.exists(aoi_id, "waterways.parquet") else None
    roads_g = storage.load_gdf(aoi_id, "edges_drive.parquet") if storage.exists(aoi_id, "edges_drive.parquet") else None
    cands = drn.candidates(water, roads_g) if water is not None and len(water) else []
    for cd in cands:
        r, c = xy_to_rowcol(grid, cd["x"], cd["y"])
        lon, lat = rowcol_to_lonlat(grid, r, c)
        cd.update(row=int(np.clip(r, 0, grid.height - 1)), col=int(np.clip(c, 0, grid.width - 1)),
                  lon=round(float(lon), 6), lat=round(float(lat), 6))
    storage.put_json(aoi_id, "drain_candidates.json", cands)
    if not cands:
        warnings.append("No OSM drains, canals or culverts here; drain priority list unavailable")
    meta["urban"] = {"depressions": int(len(st["v_dep"]) - 1), "depression_volume_m3": round(float(st["v_dep"].sum())),
                     "drain_candidates": len(cands),
                     "dem": dem_src, "note": "ponding is a screening estimate (no pipes, no merging of overflowing depressions)"}


def _overlays(aoi_id: str) -> None:
    hand = storage.load_layers(aoi_id, "hydro30")["hand"]
    storage.save_png(aoi_id, "hand", to_png(np.where(hand <= 20, hand, np.nan), "hand", 0, 20))


ACTIVE: set[str] = set()  # areas being prepared in this process (a "preparing" area not in here was interrupted)


def prepare_area(aoi: AOI, force: frozenset[str] = frozenset()) -> dict:
    """Idempotent: steps whose outputs exist are skipped unless named in `force` (e.g. {"lsi", "network"})."""
    ACTIVE.add(aoi.aoi_id)
    try:
        return _prepare(aoi, force)
    finally:
        ACTIVE.discard(aoi.aoi_id)


def _prepare(aoi: AOI, force: frozenset[str]) -> dict:
    t0 = time.time()
    aoi_id, grid = aoi.aoi_id, make_grid(aoi.bbox)
    prev = fs.get_aoi(aoi_id) or {}
    warnings: list[str] = []
    meta: dict = {k: v for k, v in (prev.get("meta") or {}).items() if k != "timings_s"}  # keep skipped steps' meta
    status: dict[str, str] = {}

    timings: dict[str, float] = {}

    step_warn: dict[str, list[str]] = dict(prev.get("step_warnings") or {})

    def run(name: str, fn, *args) -> None:
        t = time.time()
        mine: list[str] = []  # this step's warnings replace the ones it produced last time
        args = tuple(mine if a is warnings else a for a in args)
        try:
            fn(*args)
            status[name] = "ready"
        except Exception as e:
            log.exception("prepare_area %s failed", name)
            status[name] = "error"
            mine.append(f"{name} failed: {e}")
        step_warn[name] = mine
        timings[name] = round(time.time() - t, 1)
        fs.update_aoi(aoi_id, {f"status.{name}": status[name]})

    storage.save_grid(aoi_id, grid)
    fs.update_aoi(aoi_id, {"grid": grid.to_dict(), "state": "preparing"})
    images = ees.layer_images(grid, bare_earth=_bare(aoi))
    tasks = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for g in EE_GROUPS:
            if storage.exists(aoi_id, f"{g}.npz") and g not in force:
                status[g] = "ready"
            else:
                tasks.append(ex.submit(run, g, _ee_group, aoi_id, grid, images, g, warnings, meta))
        if storage.exists(aoi_id, "buildings.parquet") and "buildings" not in force:
            status["buildings"] = "ready"
        else:
            tasks.append(ex.submit(run, "buildings", _buildings, aoi, grid, warnings))
        tasks.append(ex.submit(run, "osm", _osm, aoi_id, grid, warnings))
        for t in tasks:
            t.result()
    if not storage.exists(aoi_id, "derived.npz") or "derived" in force:
        run("derived", _derived, aoi_id, grid, warnings)
    else:
        status["derived"] = "ready"
    if status.get("hydro30") == "ready":
        if storage.exists(aoi_id, "reaches.json") and "hydrology" not in force:
            status["hydrology"] = "ready"
        else:
            run("hydrology", _hydrology, aoi_id, grid, warnings, meta)
        run("overlays", _overlays, aoi_id)
        if storage.exists(aoi_id, "png/fsi.png") and "fsi" not in force:
            status["fsi"] = "ready"
        else:
            run("fsi", _fsi, aoi_id, meta)
        if storage.exists(aoi_id, "png/lsi_static.png") and "lsi" not in force:
            status["lsi"] = "ready"
        elif status.get("derived") == "ready":
            run("lsi", _lsi, aoi, grid, warnings, meta)
    if storage.exists(aoi_id, "buildings_proxy.parquet") and "building_proxy" not in force:
        status["building_proxy"] = "ready"
    elif status.get("buildings") == "ready" and status.get("population") == "ready":
        run("building_proxy", _building_proxy, aoi_id, grid, meta)
    if storage.exists(aoi_id, "shelters.json") and "network" not in force:
        status["network"] = "ready"
    elif status.get("building_proxy") == "ready" and status.get("osm") == "ready":
        run("network", _network, aoi, grid, warnings, meta)
    # every area: street-waterlogging hollows and drain candidates (applied only where built-up, engines/profile.py)
    if storage.exists(aoi_id, "pluvial.npz") and "urban" not in force:
        status["urban"] = "ready"
    elif status.get("network") == "ready":
        run("urban", _urban, aoi, grid, warnings, meta)

    secs = round(time.time() - t0, 1)
    warnings = list(dict.fromkeys(w for ws in step_warn.values() for w in ws))
    state = "ready" if all(v == "ready" for v in status.values()) else "partial"
    fs.update_aoi(aoi_id, {"status": status, "state": state, "warnings": warnings, "step_warnings": step_warn,
                           "meta": {**meta, "timings_s": timings},
                           "prepare_seconds": secs, "prepared_at": datetime.now(timezone.utc)})
    log.info("prepare_area %s: %s in %ss", aoi_id, state, secs)
    # pre-monsoon improvements (pipeline/improvements.py) run after the area is usable: the map opens without waiting
    # for satellite checks and web search; the map's "Finding fixes" chip follows their progress
    if status.get("network") == "ready" and status.get("hydrology") == "ready" and (
            not storage.exists(aoi_id, "improvements.json") or "improvements" in force):
        from app.pipeline import improvements as impv
        impv.start(aoi_id)
    return {"state": state, "status": status, "warnings": warnings, "meta": {**meta, "timings_s": timings}, "seconds": secs}
