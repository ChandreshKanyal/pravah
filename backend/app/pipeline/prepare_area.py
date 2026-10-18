"""S1.12: fetch, align and cache every static layer for one AOI. Idempotent: groups already in GCS are skipped."""
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import osmnx as ox
from google.api_core.exceptions import NotFound
from rasterio.features import rasterize
from rasterio.transform import Affine
from scipy.ndimage import distance_transform_edt

from app.config import get_settings
from app.engines import buildings as bld, crowding, fsi as fsi_engine, hydrology as hy, population, rainfall
from app.engines import drains as drn, pluvial, roads, shelters as shel
from app.engines.grid import lonlat_bounds, make_grid, rowcol_to_lonlat, terrain, xy_to_rowcol
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
        from app.services import places
        storage.put_json(aoi_id, "places.json", places.from_gdf(b["places"]))  # runs never fetch them
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


def _merit(grid: GridSpec) -> dict[str, np.ndarray]:
    return ees.fetch_merit_native(hy.make_hydro_grid(lonlat_bounds(grid)))


def _hydrology(aoi_id: str, grid: GridSpec, warnings: list[str], meta: dict, merit=None) -> None:
    """S2: native-grid D8 hydrology, reaches, SRC tables, hotspots; mapped to the 30 m grid (S2.12). `merit`: the
    MERIT download already started (a Future), else it is fetched here."""
    cfg = get_settings()
    hg = hy.make_hydro_grid(lonlat_bounds(grid))
    m = merit.result() if merit is not None else ees.fetch_merit_native(hg)
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


def _road_tables(aoi_id: str, grid: GridSpec) -> tuple[dict, list[str], np.ndarray]:
    """(routable edge tables per travel mode (S7.1-S7.4), warnings, slope): the slow part of the network step. It needs
    only the OSM roads and the terrain, so preparation runs it while the buildings download."""
    t = storage.load_layers(aoi_id, "terrain")

    def one(mode: str):
        try:
            G = storage.load_graph(aoi_id, f"G_{mode}.graphml")
        except NotFound:
            return None
        if mode == "drive":
            G = ox.add_edge_travel_times(roads.add_speeds(G))
        return roads.edge_table(ox.project_graph(G, to_crs=grid.crs), grid, mode, t["dem"], t["slope_deg"])
    with ThreadPoolExecutor(2) as ex:
        got = dict(zip(("walk", "drive"), ex.map(one, ("walk", "drive"))))
    warnings = [f"No OSM {m} network; {m} routing unavailable" for m, tab in got.items() if tab is None]
    return {m: tab for m, tab in got.items() if tab is not None}, warnings, t["slope_deg"]


def _network(aoi: AOI, grid: GridSpec, warnings: list[str], meta: dict, road_tables=None) -> None:
    """S7.1-S7.6 + S9: routable edge tables, crowding grid and edge crowding, shelters and medical facilities.
    `road_tables`: a Future of _road_tables started ahead, else they are built here."""
    aoi_id = aoi.aoi_id
    with ThreadPoolExecutor(4) as ex:
        f_hand = ex.submit(lambda: storage.load_layers(aoi_id, "hydro30")["hand"])
        f_b = ex.submit(storage.load_gdf, aoi_id, "buildings_proxy.parquet")
        f_pois = ex.submit(storage.load_gdf, aoi_id, "pois.parquet")
        tables, tw, slope_deg = road_tables.result() if road_tables is not None else _road_tables(aoi_id, grid)
        hand, b, pois = f_hand.result(), f_b.result(), f_pois.result().to_crs(grid.crs)
    warnings.extend(tw)

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
    saves = ThreadPoolExecutor(8)  # this step's uploads go out in parallel while it keeps computing
    jobs = [saves.submit(storage.save_layers, aoi_id, "crowding", {"crowd": crowd}, grid),
            saves.submit(lambda: storage.save_png(aoi_id, "crowd", to_png(np.where(crowd > 0.05, crowd, np.nan), "risk", 0, 1)))]
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
    jobs.append(saves.submit(storage.put_json, aoi_id, "crowd_hotspots.json", [{k: v for k, v in h.items() if k not in ("x", "y")} for h in hot]))

    for mode, (edges, nodes) in tables.items():
        edges["crowd_e"] = [crowding.edge_crowd(crowd, cells, n) for cells, n in zip(edges["cells"], edges["narrowness"])]
        jobs += [saves.submit(storage.save_gdf, aoi_id, f"edges_{mode}.parquet", edges),
                 saves.submit(storage.save_gdf, aoi_id, f"nodes_{mode}.parquet", nodes)]

    # S7.5-S7.6 shelters and medical
    w, s, e, n = aoi.bbox
    in_aoi = lambda d: ((d["lon"] >= w) & (d["lon"] <= e) & (d["lat"] >= s) & (d["lat"] <= n)).to_numpy()  # noqa: E731
    sh, med = shel.from_pois(pois, b)
    n_osm = len(sh)
    n_proper = sum(1 for x in sh if x["kind"] != shel.WORSHIP)  # halls of worship need confirmation
    if n_proper < shel.MIN_OSM_SHELTERS:
        warnings.append(f"Only {n_proper} schools/community halls in OpenStreetMap here ({n_osm - n_proper} places of "
                        "worship); added unverified large-building candidates. Add or confirm shelters with local authorities.")
        sh += shel.candidate_large_buildings(b, hand, slope_deg, in_aoi, shel.MAX_CANDIDATES - n_proper)
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
                         "primary": bool(w <= lon <= e and s <= lat <= n), **nodes_})
        out.append(recs)
    meta["network"] = {m: {"nodes": int(len(nd)), "edges": int(len(ed)), "bridges": int(ed["bridge"].sum())}
                       for m, (ed, nd) in tables.items()}
    meta["bridges"] = build_bridges(aoi_id, grid, warnings, {m: ed for m, (ed, _) in tables.items()})
    meta["shelters"] = {"osm": n_osm, "total": len(out[0]), "medical": len(out[1])}
    # shelters.json last: it marks the step done (a resumed preparation skips the step when it exists)
    for j in jobs + [saves.submit(storage.put_json, aoi_id, "medical.json", out[1])]:
        j.result()
    saves.shutdown()
    storage.put_json(aoi_id, "shelters.json", out[0])


def _opt_gdf(aoi_id: str, name: str):
    try:
        return storage.load_gdf(aoi_id, name)
    except NotFound:
        return None


def build_bridges(aoi_id: str, grid: GridSpec, warnings: list[str], edges: dict | None = None) -> dict:
    """Real bridge spans with deck heights and their links to the routable edges (engines/bridges.py) -> bridges.json.
    `edges`: {mode: edge table} just built (else read from storage)."""
    from app.engines import bridges as brg
    with ThreadPoolExecutor(4) as ex:
        f_ways = ex.submit(_opt_gdf, aoi_id, "bridge_ways.parquet")
        f_h30 = ex.submit(storage.load_layers, aoi_id, "hydro30")
        f_water = ex.submit(_opt_gdf, aoi_id, "waterways.parquet")
        f_edges = {m: ex.submit(_opt_gdf, aoi_id, f"edges_{m}.parquet") for m in ("walk", "drive") if edges is None}
        ways, h30, water = f_ways.result(), f_h30.result(), f_water.result()
        edges = edges if edges is not None else {m: f.result() for m, f in f_edges.items() if f.result() is not None}
    if ways is None:
        try:
            ways = osm.bridge_ways(lonlat_bounds(grid))
            storage.save_gdf(aoi_id, "bridge_ways.parquet", ways)
        except Exception as e:
            warnings.append(f"OSM bridges unavailable: {e}")
            return {"spans": 0}
    water = water.to_crs(grid.crs) if water is not None else None
    water_lines = [g for g in water.geometry if g is not None and g.geom_type in ("LineString", "MultiLineString")] if water is not None else None
    spans = brg.spans(ways.to_crs(grid.crs) if len(ways) else None, grid, h30["hand"], h30["reach_id"],
                      h30.get("dist_stream_m"), water_lines)
    links = {}
    for m in ("walk", "drive"):
        if m in edges:
            links[m] = {str(e): ks for e, ks in brg.link_edges(spans, edges[m].reset_index(drop=True).geometry).items()}
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
    """Bare-earth terrain (FABDEM) for every new area: the surface model's building tops make false slopes
    (at building edges) and false dams for water. Areas prepared as "river" before 17 Oct keep Copernicus GLO-30 so
    their cached layers stay consistent."""
    return aoi.mode != "river"


def _urban(aoi: AOI, grid: GridSpec, warnings: list[str], meta: dict, fab=None) -> None:
    """S13 static part (urban mode): depression analysis on the filled DEM and drain/culvert candidates. `fab`: the
    FABDEM download already started (a Future), else it is fetched here."""
    aoi_id = aoi.aoi_id
    try:
        dem = fab.result() if fab is not None else ees.fetch_fabdem(grid)
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
    """Idempotent: steps whose outputs exist are skipped unless named in `force` (e.g. {"network"})."""
    ACTIVE.add(aoi.aoi_id)
    try:
        return _prepare(aoi, force)
    finally:
        ACTIVE.discard(aoi.aoi_id)


STEP_ORDER = EE_GROUPS + ["buildings", "osm", "derived", "hydrology", "overlays", "fsi", "building_proxy", "network", "urban"]


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
    # a step whose output exists is skipped unless forced (resumed or re-prepared areas); checked in parallel up front
    marks = {**{g: f"{g}.npz" for g in EE_GROUPS}, "buildings": "buildings.parquet", "derived": "derived.npz",
             "hydrology": "reaches.json", "fsi": "png/fsi.png", "building_proxy": "buildings_proxy.parquet",
             "network": "shelters.json", "urban": "pluvial.npz", "improvements": "improvements.json"}
    with ThreadPoolExecutor(12) as ex:
        have = dict(zip(marks, ex.map(lambda f: storage.exists(aoi_id, f), marks.values())))
    todo = lambda step: step in force or not have[step]  # noqa: E731
    if todo("improvements"):
        from app.pipeline import improvements as impv
        impv.prefetch_reported(aoi_id, aoi.name, aoi.bbox)  # the fixes list's web search runs alongside the downloads
    images = ees.layer_images(grid, bare_earth=_bare(aoi))

    # Each step starts as soon as the steps it reads are done (18 Oct; they ran one after another once every download
    # had finished): hydrology, susceptibility and the road raster run while the buildings download, the MERIT and
    # FABDEM downloads start with the others, and the road tables (the slow part of the network step) are built from
    # the OSM roads and the terrain meanwhile. Every task fits in the pool at once, so waiting tasks cannot starve it.
    ex = ThreadPoolExecutor(max_workers=24)
    F: dict = {}

    def after(deps: list[str], fn):
        def go():
            for d in deps:
                if d in F:
                    F[d].result()  # a step records its own error; waiting is all that matters here
            return fn()
        return ex.submit(go)

    def skip_or(step: str, cond, fn):
        """Run `fn` if the step is needed and `cond()` holds; a step not needed counts as ready."""
        def go():
            if not todo(step):
                status[step] = "ready"
            elif cond():
                fn()
        return go

    try:
        for g in EE_GROUPS:
            if todo(g):
                F[g] = ex.submit(run, g, _ee_group, aoi_id, grid, images, g, warnings, meta)
            else:
                status[g] = "ready"
        if todo("buildings"):
            F["buildings"] = ex.submit(run, "buildings", _buildings, aoi, grid, warnings)
        else:
            status["buildings"] = "ready"
        F["osm"] = ex.submit(run, "osm", _osm, aoi_id, grid, warnings)
        merit = ex.submit(_merit, grid) if todo("hydrology") else None
        fab = ex.submit(ees.fetch_fabdem, grid) if todo("urban") else None
        tables = after(["osm", "terrain"], lambda: _road_tables(aoi_id, grid)) if todo("network") else None
        ready = lambda *steps: all(status.get(x) == "ready" for x in steps)  # noqa: E731

        F["derived"] = after(["osm"], skip_or("derived", lambda: True, lambda: run("derived", _derived, aoi_id, grid, warnings)))
        # the river steps need hydro30; without it they get no status at all (as before)
        F["hydrology"] = after(["hydro30"], lambda: ready("hydro30") and skip_or(
            "hydrology", lambda: True, lambda: run("hydrology", _hydrology, aoi_id, grid, warnings, meta, merit))())
        F["overlays"] = after(["hydro30"], lambda: ready("hydro30") and run("overlays", _overlays, aoi_id))
        F["fsi"] = after(["hydro30", "terrain", "landcover", "hazard_hist"], lambda: ready("hydro30") and skip_or(
            "fsi", lambda: True, lambda: run("fsi", _fsi, aoi_id, meta))())
        F["building_proxy"] = after(["buildings", "population"], skip_or(
            "building_proxy", lambda: ready("buildings", "population"), lambda: run("building_proxy", _building_proxy, aoi_id, grid, meta)))
        F["network"] = after(["building_proxy", "osm", "hydrology", "terrain"], skip_or(
            "network", lambda: ready("building_proxy", "osm"), lambda: run("network", _network, aoi, grid, warnings, meta, tables)))
        # every area: street-waterlogging hollows and drain candidates (applied only where built-up, engines/profile.py)
        F["urban"] = after(["network", "landcover", "terrain"], skip_or(
            "urban", lambda: ready("network"), lambda: run("urban", _urban, aoi, grid, warnings, meta, fab)))
        for f in list(F.values()):
            f.result()
    finally:
        ex.shutdown(wait=True)

    secs = round(time.time() - t0, 1)
    rank = {k: i for i, k in enumerate(STEP_ORDER)}  # warnings in step order, whichever step finished first
    warnings = list(dict.fromkeys(w for k in sorted(step_warn, key=lambda k: rank.get(k, len(rank))) for w in step_warn[k]))
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
