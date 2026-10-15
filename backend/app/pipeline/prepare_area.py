"""S1.12: fetch, align and cache every static layer for one AOI. Idempotent: groups already in GCS are skipped."""
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
import osmnx as ox
from rasterio.features import rasterize
from rasterio.transform import Affine
from scipy.ndimage import distance_transform_edt

from app.config import get_settings
from app.engines import fsi as fsi_engine, hydrology as hy, rainfall
from app.engines.grid import lonlat_bounds, make_grid, rowcol_to_lonlat, terrain
from app.engines.render import to_png, to_png_classes
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
    warnings.extend(w)
    storage.save_gdf(aoi.aoi_id, "buildings.parquet", gdf)


def _osm(aoi_id: str, grid: GridSpec, warnings: list[str]) -> None:
    bb = lonlat_bounds(grid)
    for name, net in (("G_walk.graphml", "walk"), ("G_drive.graphml", "drive")):
        if storage.exists(aoi_id, name):
            continue
        try:
            storage.save_graph(aoi_id, name, osm.graph(bb, net))
        except Exception as e:
            warnings.append(f"OSM {net} network unavailable: {e}")
    if not (storage.exists(aoi_id, "pois.parquet") and storage.exists(aoi_id, "waterways.parquet")):
        try:
            pois, water = osm.pois_and_waterways(bb)
            storage.save_gdf(aoi_id, "pois.parquet", pois)
            storage.save_gdf(aoi_id, "waterways.parquet", water)
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


def _overlays(aoi_id: str) -> None:
    hand = storage.load_layers(aoi_id, "hydro30")["hand"]
    storage.save_png(aoi_id, "hand", to_png(np.where(hand <= 20, hand, np.nan), "hand", 0, 20))


def prepare_area(aoi: AOI) -> dict:
    t0 = time.time()
    aoi_id, grid = aoi.aoi_id, make_grid(aoi.bbox)
    warnings: list[str] = []
    meta: dict = {}
    status: dict[str, str] = {}

    timings: dict[str, float] = {}

    def run(name: str, fn, *args) -> None:
        t = time.time()
        try:
            fn(*args)
            status[name] = "ready"
        except Exception as e:
            log.exception("prepare_area %s failed", name)
            status[name] = "error"
            warnings.append(f"{name} failed: {e}")
        timings[name] = round(time.time() - t, 1)
        fs.update_aoi(aoi_id, {f"status.{name}": status[name]})

    storage.save_grid(aoi_id, grid)
    fs.update_aoi(aoi_id, {"grid": grid.to_dict(), "state": "preparing"})
    images = ees.layer_images(grid)
    tasks = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for g in EE_GROUPS:
            if storage.exists(aoi_id, f"{g}.npz"):
                status[g] = "ready"
            else:
                tasks.append(ex.submit(run, g, _ee_group, aoi_id, grid, images, g, warnings, meta))
        if storage.exists(aoi_id, "buildings.parquet"):
            status["buildings"] = "ready"
        else:
            tasks.append(ex.submit(run, "buildings", _buildings, aoi, grid, warnings))
        tasks.append(ex.submit(run, "osm", _osm, aoi_id, grid, warnings))
        for t in tasks:
            t.result()
    if not storage.exists(aoi_id, "derived.npz"):
        run("derived", _derived, aoi_id, grid, warnings)
    else:
        status["derived"] = "ready"
    if status.get("hydro30") == "ready":
        if storage.exists(aoi_id, "reaches.json"):
            status["hydrology"] = "ready"
        else:
            run("hydrology", _hydrology, aoi_id, grid, warnings, meta)
        run("overlays", _overlays, aoi_id)
        if storage.exists(aoi_id, "png/fsi.png"):
            status["fsi"] = "ready"
        else:
            run("fsi", _fsi, aoi_id, meta)
    # Later stages hook in here:, S5 LSI static, S6.1-S6.3, S7.1-S7.6, S9 crowding.

    secs = round(time.time() - t0, 1)
    state = "ready" if all(v == "ready" for v in status.values()) else "partial"
    fs.update_aoi(aoi_id, {"status": status, "state": state, "warnings": warnings, "meta": {**meta, "timings_s": timings},
                           "prepare_seconds": secs, "prepared_at": datetime.now(timezone.utc)})
    log.info("prepare_area %s: %s in %ss", aoi_id, state, secs)
    return {"state": state, "status": status, "warnings": warnings, "meta": {**meta, "timings_s": timings}, "seconds": secs}
