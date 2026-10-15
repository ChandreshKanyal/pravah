"""run_pipeline(params): fixed order S10 -> S3 -> S5 -> S6 -> S8 -> S15 (stages are added as they are built)."""
import io
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np

from app.config import get_settings
from app.engines import flood, hydrology as hy, landslide as ls, rainfall
from app.engines.grid import lonlat_bounds, lonlat_to_rowcol, corner_lonlats
from app.engines.render import DEPTH_COLORS, DEPTH_EDGES, WATER_COLOR, to_png_binned, to_png_classes
from app.models.grid import GridSpec
from app.models.run import RunResult
from app.models.scenario import RainSource, ScenarioParams
from app.services import firestore as fs
from app.services import storage

log = logging.getLogger(__name__)


class AreaNotReady(RuntimeError):
    pass


@dataclass
class Area:
    """Static per-AOI data, loaded once per process."""
    aoi_id: str
    grid: GridSpec
    hgrid: hy.HydroGrid
    hand: np.ndarray
    perm: np.ndarray
    reach_id_30: np.ndarray
    lc_class: np.ndarray
    reaches: list[dict]
    native: dict[str, np.ndarray]
    hotspots: list[dict]
    slope_deg: np.ndarray
    lsi_static: np.ndarray | None
    lsi_edges: list[float] | None
    src_cache: dict[float, list[dict]] = field(default_factory=dict)


@lru_cache(maxsize=4)
def load_area(aoi_id: str) -> Area:
    if not storage.exists(aoi_id, "reaches.json"):
        raise AreaNotReady(f"AOI {aoi_id} is not prepared yet")
    h30 = storage.load_layers(aoi_id, "hydro30")
    sus = storage.load_layers(aoi_id, "susceptibility") if storage.exists(aoi_id, "susceptibility.npz") else {}
    return Area(
        aoi_id=aoi_id,
        grid=storage.load_grid(aoi_id),
        hgrid=hy.HydroGrid(**storage.get_json(aoi_id, "hydro_grid.json")),
        hand=h30["hand"],
        perm=flood.permanent_water(storage.load_layers(aoi_id, "hazard_hist")["gsw_occ"]),
        reach_id_30=h30["reach_id"],
        lc_class=storage.load_layers(aoi_id, "landcover")["lc_class"],
        reaches=storage.get_json(aoi_id, "reaches.json"),
        native=storage.load_layers(aoi_id, "hydro_native"),
        hotspots=storage.get_json(aoi_id, "hotspots.json"),
        slope_deg=storage.load_layers(aoi_id, "terrain")["slope_deg"],
        lsi_static=sus.get("lsi_static"),
        lsi_edges=sus["lsi_edges"].tolist() if "lsi_edges" in sus else None,
    )


def get_src(area: Area, n: float) -> list[dict]:
    """SRC tables ordered by reach_id; cached in memory and in GCS keyed by Manning's n."""
    n = round(n, 3)
    if n not in area.src_cache:
        name = f"src_n{n:.3f}.json"
        if storage.exists(area.aoi_id, name):
            tables = storage.get_json(area.aoi_id, name)
        else:
            nat = area.native
            tables = hy.src_tables(nat["hnd"], nat["catch_reach"], nat["slope"], area.reaches, area.hgrid.cell_area, n)
            storage.put_json(area.aoi_id, name, tables)
        area.src_cache[n] = [tables[str(r["reach_id"])] for r in area.reaches]
    return area.src_cache[n]


def reach_params(area: Area, c_table: list[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """C_reach (mean C over hydro cells upstream of the reach end), tc_h and A_loc per reach."""
    hg = area.hgrid
    rows, cols = np.indices((hg.height, hg.width))
    lon = hg.lon0 + (cols.ravel() + 0.5) * hg.cell_deg
    lat = hg.lat0 - (rows.ravel() + 0.5) * hg.cell_deg
    r30, c30 = lonlat_to_rowcol(area.grid, lon, lat)
    inside = (r30 >= 0) & (r30 < area.grid.height) & (c30 >= 0) & (c30 < area.grid.width)
    c30_grid = rainfall.runoff_c(area.lc_class, c_table)
    c_nat = np.full(lon.size, np.nan, np.float32)
    c_nat[inside] = c30_grid[r30[inside], c30[inside]]
    ok = np.isfinite(c_nat)
    down = area.native["downstream"].astype(np.int64)
    acc_c = hy.accumulate(down, np.where(ok, c_nat, 0))
    acc_n = hy.accumulate(down, ok.astype(float))
    grid_mean = float(np.nanmean(c_nat)) if ok.any() else 0.5
    last = np.array([r["cells"][-1] for r in area.reaches])
    C = np.where(acc_n[last] > 0, acc_c[last] / np.maximum(acc_n[last], 1), grid_mean)
    A_loc = np.array([r["A_loc_km2"] for r in area.reaches])
    S = np.array([r["S"] for r in area.reaches])
    return np.clip(C, 0.10, 0.95), rainfall.tc_hours(A_loc, S), A_loc


def rain_series(p: ScenarioParams) -> tuple[list[float], str, list[str]]:
    """S10 builds forecast/worst/best/historical series; until then only manual rain is available."""
    warnings = []
    if p.rain_source != RainSource.manual:
        warnings.append(f"Rain source '{p.rain_source.value}' is not available yet; used manual "
                        f"{p.manual_intensity_mm_h:g} mm/h instead")
    series = rainfall.manual_series(p.manual_intensity_mm_h, p.duration_h, p.hyetograph)
    label = f"Manual {p.manual_intensity_mm_h:g} mm/h for {p.duration_h} h ({p.hyetograph})"
    return series, label, warnings


def run_pipeline(p: ScenarioParams) -> RunResult:
    t0 = time.time()
    timings: dict[str, float] = {}
    area = load_area(p.aoi_id)
    run_id = uuid.uuid4().hex[:12]

    rain, rain_label, warnings = rain_series(p)
    C, tc_h, A_loc = reach_params(area, get_settings().runoff_c)
    h, _Q = flood.hourly_envelope(rain, tc_h, C, A_loc, get_src(area, p.manning_n), p.river_offset_m)
    depth = flood.depth_stack(h, area.reach_id_30, area.hand, area.perm)
    timings["flood"] = round(time.time() - t0, 2)

    lsi_dyn = None  # S5.6: rainfall-modulated susceptibility classes per hour
    if area.lsi_static is not None:
        lsi_dyn = ls.lsi_dynamic_classes(area.lsi_static, area.lsi_edges, rain, area.slope_deg)
    else:
        warnings.append("Landslide susceptibility not prepared for this area")

    t1 = time.time()
    pngs = {f"depth_h{t + 1}": to_png_binned(depth[t], DEPTH_EDGES, DEPTH_COLORS, nan_color=WATER_COLOR)
            for t in range(depth.shape[0])}
    if lsi_dyn is not None:
        pngs.update({f"lsi_h{t + 1}": to_png_classes(lsi_dyn[t]) for t in range(lsi_dyn.shape[0])})
    buf = io.BytesIO()
    np.savez_compressed(buf, depth=depth.astype(np.float16))
    lbuf = io.BytesIO()
    if lsi_dyn is not None:
        np.savez_compressed(lbuf, lsi_dyn_class=lsi_dyn)
    with ThreadPoolExecutor(8) as ex:
        jobs = [ex.submit(storage.put_run, run_id, f"png/{k}.png", v, "image/png") for k, v in pngs.items()]
        jobs.append(ex.submit(storage.put_run, run_id, "depth.npz", buf.getvalue()))
        if lsi_dyn is not None:
            jobs.append(ex.submit(storage.put_run, run_id, "lsi.npz", lbuf.getvalue()))
        for j in jobs:
            j.result()
    timings["render_upload"] = round(time.time() - t1, 2)

    worst = depth[-1]
    hotspots = []
    for hs in area.hotspots:  # S3.9: local depth and stage at the worst hour
        r, c = lonlat_to_rowcol(area.grid, hs["lon"], hs["lat"])
        r, c = int(r), int(c)
        inside = 0 <= r < area.grid.height and 0 <= c < area.grid.width
        rid = int(area.reach_id_30[r, c]) if inside else -1
        d = float(worst[r, c]) if inside else 0.0
        channel = bool(np.isnan(d))  # permanent water: the river itself, not flood
        hotspots.append({**hs, "depth_m": None if channel else round(d, 2), "in_river_channel": channel,
                         "stage_m": round(float(h[rid, -1]), 2) if rid >= 0 else None})

    result = RunResult(
        run_id=run_id, aoi_id=p.aoi_id, params=p, created_at=datetime.now(timezone.utc),
        rain_series_mm_h=rain, rain_label=rain_label,
        stage_by_reach_m={str(r["reach_id"]): h[i].round(2).tolist() for i, r in enumerate(area.reaches)},
        flooded_area_km2_by_hour=[round(flood.flooded_area_km2(depth[t], area.grid.cell), 3) for t in range(len(rain))],
        depth_png_urls=[f"/api/runs/{run_id}/layers/{k}.png" for k in pngs if k.startswith("depth_")],
        lsi_png_url=f"/api/runs/{run_id}/layers/lsi_h{len(rain)}.png" if lsi_dyn is not None else "",
        overlay_bounds=lonlat_bounds(area.grid), overlay_corners=corner_lonlats(area.grid),
        hotspots=hotspots, warnings=warnings,
    )
    timings["total"] = round(time.time() - t0, 2)
    result.timings_s = timings
    fs.set_doc("runs", run_id, result.model_dump(mode="json"))
    log.info("run %s: %s", run_id, timings)
    return result
