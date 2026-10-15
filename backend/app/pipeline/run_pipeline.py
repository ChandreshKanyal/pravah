"""run_pipeline(params): fixed order S10 -> S3 -> S5 -> S6 -> S8 -> S15 (stages are added as they are built)."""
import io
import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np

from app.config import get_settings
from app.engines import exposure as ex_engine, flood, hydrology as hy, landslide as ls, population, rainfall
from app.engines.grid import corner_lonlats, lonlat_bounds, lonlat_to_rowcol, rowcol_to_lonlat
from app.engines.render import DEPTH_COLORS, DEPTH_EDGES, WATER_COLOR, to_png_binned, to_png_classes
from app.models.grid import GridSpec
from app.models.run import ExposureSummary, RunResult, TriageRow
from app.models.scenario import RainSource, ScenarioParams
from app.services import firestore as fs
from app.services import storage
from app.pipeline import evac

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
    dist_stream_m: np.ndarray
    bld: dict[str, np.ndarray] | None  # building arrays from buildings_proxy.parquet
    pop_unattr: np.ndarray | None
    lsi_class: np.ndarray | None
    dist_road_m: np.ndarray
    shelters: list[dict]
    networks: dict
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
        dist_stream_m=h30["dist_stream_m"],
        bld=_load_buildings(aoi_id),
        pop_unattr=storage.load_layers(aoi_id, "population").get("pop_unattributed"),
        lsi_class=sus.get("lsi_class"),
        dist_road_m=storage.load_layers(aoi_id, "derived")["dist_road_m"],
        shelters=storage.get_json(aoi_id, "shelters.json") if storage.exists(aoi_id, "shelters.json") else [],
        networks={m: evac.load_network(storage.load_gdf(aoi_id, f"edges_{m}.parquet"),
                                       storage.load_gdf(aoi_id, f"nodes_{m}.parquet"))
                  for m in ("walk", "drive") if storage.exists(aoi_id, f"edges_{m}.parquet")},
    )


def _load_buildings(aoi_id: str) -> dict[str, np.ndarray] | None:
    if not storage.exists(aoi_id, "buildings_proxy.parquet"):
        return None
    b = storage.load_gdf(aoi_id, "buildings_proxy.parquet")
    cols = ["bid", "lon", "lat", "row", "col", "structure_class", "fragility", "confidence", "pop_base"]
    return {c: b[c].to_numpy() for c in cols}


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


def area_centroid(area: Area) -> tuple[float, float]:
    w, s, e, n = lonlat_bounds(area.grid)
    return (w + e) / 2, (s + n) / 2


def historical_max_mm(area: Area) -> float:
    """CHIRPS max daily total near the AOI (Earth Engine data, cached per AOI in GCS)."""
    if storage.exists(area.aoi_id, "chirps_max.json"):
        return float(storage.get_json(area.aoi_id, "chirps_max.json")["mm"])
    lon, lat = area_centroid(area)
    from app.services import earth_engine as ees
    mm = ees.chirps_max_daily_mm(lon, lat)
    storage.put_json(area.aoi_id, "chirps_max.json", {"mm": mm})
    return mm


def rain_series(p: ScenarioParams, area: Area) -> tuple[list[float], str, list[str]]:
    """S10.5: forecast / worst / best / historical_extreme / manual hourly series (mm/h) and a human label."""
    from datetime import date as _date
    from app.services.weather import get_provider
    H, warnings = p.duration_h, []
    src = p.rain_source
    if src in (RainSource.forecast, RainSource.worst, RainSource.best):
        try:
            lon, lat = area_centroid(area)
            prov = get_provider()
            daily, hourly = prov.daily(lat, lon, 10), prov.hourly(lat, lon, 240)
            k = p.forecast_day_index if p.forecast_day_index is not None else rainfall.worst_day_index(daily, hourly)
            day = daily[min(k, len(daily) - 1)]["date"]
            series, start = rainfall.wettest_window(rainfall.day_hours(hourly, day), H)
            mult = {RainSource.worst: p.worst_multiplier, RainSource.best: p.best_multiplier}.get(src, 1.0)
            series = [v * mult for v in series]
            label = f"Forecast {_date.fromisoformat(day).strftime('%a %d %b')}, wettest {H} h from {start:02d}:00"
            if src != RainSource.forecast:
                label += f", {src.value} case x{mult:g}"
            if sum(series) == 0:
                warnings.append("The forecast shows no rain for this window; try historical extreme or manual rain")
            return series, label, warnings
        except Exception as e:  # provider down or no key: fall back, never fail the run
            warnings.append(f"Forecast unavailable ({e.__class__.__name__}); used manual rain instead")
    elif src == RainSource.historical_extreme:
        try:
            mm = historical_max_mm(area)
            series = rainfall.distribute_total(mm, H, p.hyetograph)
            return series, f"Historical extreme: {mm:.0f} mm/day (CHIRPS 2001-2024 max within 5 km) over {H} h", warnings
        except Exception as e:
            warnings.append(f"Historical extreme unavailable ({e.__class__.__name__}); used manual rain instead")
    series = rainfall.manual_series(p.manual_intensity_mm_h, H, p.hyetograph)
    label = f"Manual {p.manual_intensity_mm_h:g} mm/h for {H} h ({p.hyetograph.replace('_', ' ')})"
    return series, label, warnings


def screening(area: Area, daily: list[dict], hourly: list[dict], duration_h: int) -> list[dict]:
    """S10.6: per forecast day, one-reach (largest A_loc) envelope on the wettest window -> badge."""
    C, tc_h, A_loc = reach_params(area, get_settings().runoff_c)
    r = int(np.argmax(A_loc))
    src = [get_src(area, get_settings().manning_n)[r]]
    out = []
    for d in daily:
        win, _ = rainfall.wettest_window(rainfall.day_hours(hourly, d["date"]), duration_h)
        h, _ = flood.hourly_envelope(win, tc_h[r:r + 1], C[r:r + 1], A_loc[r:r + 1], src)
        stage = float(h.max())
        badge = "high" if stage >= 3 else "elevated" if stage >= 1 else "low"
        out.append({"date": d["date"], "precip_mm": d["precip_mm"], "max_stage_m": round(stage, 2), "badge": badge})
    return out


def run_pipeline(p: ScenarioParams) -> RunResult:
    t0 = time.time()
    timings: dict[str, float] = {}
    area = load_area(p.aoi_id)
    run_id = uuid.uuid4().hex[:12]

    rain, rain_label, warnings = rain_series(p, area)
    C, tc_h, A_loc = reach_params(area, get_settings().runoff_c)
    h, _Q = flood.hourly_envelope(rain, tc_h, C, A_loc, get_src(area, p.manning_n), p.river_offset_m)
    depth = flood.depth_stack(h, area.reach_id_30, area.hand, area.perm)
    timings["flood"] = round(time.time() - t0, 2)

    lsi_dyn = None  # S5.6: rainfall-modulated susceptibility classes per hour
    if area.lsi_static is not None:
        cfg = get_settings()
        lsi_dyn = ls.lsi_dynamic_classes(area.lsi_static, area.lsi_edges, rain, area.slope_deg, g_slope=cfg.lsi_g_slope,
                                         g_min=cfg.lsi_g_min, g_max=cfg.lsi_g_max)
    else:
        warnings.append("Landslide susceptibility not prepared for this area")

    t2 = time.time()
    exposure, triage_rows, queue, ctx = _exposure(area, p, depth, lsi_dyn, warnings)
    timings["exposure"] = round(time.time() - t2, 2)

    t3 = time.time()
    ev = evac.plan(area, p, depth, lsi_dyn, h, ctx, warnings) if ctx else {}
    timings["routing"] = round(time.time() - t3, 2)

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
        jobs.append(ex.submit(storage.put_run, run_id, "verification.json", json.dumps(queue).encode(), "application/json"))
        for k in ("roads", "routes"):
            if ev.get(f"{k}_geojson"):
                jobs.append(ex.submit(storage.put_run, run_id, f"{k}.geojson", ev[f"{k}_geojson"].encode(),
                                      "application/geo+json"))
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
        hotspots=hotspots, warnings=warnings, exposure=exposure, triage=triage_rows,
        shelters=ev.get("shelters", []), bridges=ev.get("bridges", []),
        capacity_gap_people=ev.get("capacity_gap_people", 0), assembly_points=ev.get("assembly_points", []),
        staging_points=ev.get("staging_points", []), routes=ev.get("routes_summary", []),
        people_to_evacuate=ev.get("people_to_evacuate", 0),
        roads_geojson_url=f"/api/runs/{run_id}/files/roads.geojson" if ev else "",
        routes_geojson_url=f"/api/runs/{run_id}/files/routes.geojson" if ev else "",
    )
    timings["total"] = round(time.time() - t0, 2)
    result.timings_s = timings
    fs.set_doc("runs", run_id, result.model_dump(mode="json"))
    fs.update_aoi(p.aoi_id, {"latest_run_id": run_id})
    log.info("run %s: %s", run_id, timings)
    return result


def _exposure(area: Area, p: ScenarioParams, depth: np.ndarray, lsi_dyn: np.ndarray | None,
              warnings: list[str]) -> tuple[ExposureSummary, list[TriageRow], list[dict], dict]:
    """S6.4-S6.9 at run time: scaled population, per-hour exposure, risk at the worst hour, triage, clusters, queue."""
    if area.bld is None or area.pop_unattr is None:
        warnings.append("Buildings not prepared for this area; exposure unavailable")
        return ExposureSummary(), [], [], {}
    b = area.bld
    base_total = float(b["pop_base"].sum() + area.pop_unattr.sum())
    k = population.scale_factor(base_total, p.pop_multiplier, p.pop_total_override)
    pop_b, pop_un = b["pop_base"] * k, area.pop_unattr * k
    share = float(b["pop_base"].sum()) / base_total if base_total else 0.0
    if share < 0.5:
        warnings.append(f"Only {share:.0%} of residents could be placed in mapped buildings (Open Buildings coverage); "
                        "the rest are counted from the population grid")
    rows = np.clip(b["row"].astype(int), 0, area.grid.height - 1)
    cols = np.clip(b["col"].astype(int), 0, area.grid.width - 1)
    ph = ex_engine.per_hour(depth, lsi_dyn, rows, cols, pop_b, pop_un)
    d_w, ls_w = ph["d_b"][-1], ph["ls_b"][-1]
    R, risk, _reason = ex_engine.building_risk(d_w, b["fragility"], area.dist_stream_m[rows, cols], ls_w)
    struct = b["structure_class"]
    exposed = (d_w >= ex_engine.WET_M) | (ls_w >= 4)
    to_ll = lambda r, c: rowcol_to_lonlat(area.grid, r, c)  # noqa: E731
    cl = ex_engine.clusters(rows, cols, pop_b, R, risk, struct, d_w, exposed, depth[-1], pop_un,
                            block=10, to_lonlat=to_ll)
    summary = ExposureSummary(
        total_pop=int(round(pop_b.sum() + pop_un.sum())),
        exposed_pop_by_hour=ph["exposed_pop_by_hour"],
        exposed_by_depth_band=ph["exposed_by_depth_band"],
        landslide_exposed_pop_by_hour=ph["landslide_exposed_pop_by_hour"],
        buildings_by_risk={c: int(np.count_nonzero(risk == c)) for c in ex_engine.RISK_ORDER},
        clusters=cl,
    )
    tri = [TriageRow(**r) for r in ex_engine.triage(struct, risk, pop_b)]
    queue = ex_engine.verification_queue(b["bid"], R, b["confidence"], pop_b, b["lon"], b["lat"], struct)
    ctx = {"rows": rows, "cols": cols, "pop_b": pop_b, "pop_un": pop_un, "d_b": ph["d_b"], "ls_b": ph["ls_b"],
           "clusters": cl}
    return summary, tri, queue, ctx
