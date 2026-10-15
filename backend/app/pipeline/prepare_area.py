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
from app.engines.grid import lonlat_bounds, make_grid, terrain
from app.engines.render import to_png
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
        run("overlays", _overlays, aoi_id)
    # Later stages hook in here: S2 hydrology, S4 FSI, S5 LSI static, S6.1-S6.3, S7.1-S7.6, S9 crowding.

    secs = round(time.time() - t0, 1)
    state = "ready" if all(v == "ready" for v in status.values()) else "partial"
    fs.update_aoi(aoi_id, {"status": status, "state": state, "warnings": warnings, "meta": {**meta, "timings_s": timings},
                           "prepare_seconds": secs, "prepared_at": datetime.now(timezone.utc)})
    log.info("prepare_area %s: %s in %ss", aoi_id, state, secs)
    return {"state": state, "status": status, "warnings": warnings, "meta": {**meta, "timings_s": timings}, "seconds": secs}
