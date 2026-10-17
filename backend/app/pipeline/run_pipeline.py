"""run_pipeline(params): fixed order S10 -> S3 -> S5 -> S6 -> S8 -> S15 (stages are added as they are built)."""
import io
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np
from google.api_core.exceptions import NotFound

from app.config import get_settings
from app.engines import profile as prof
from app.engines import drains as drn, exposure as ex_engine, flood, hydrology as hy, pluvial, population, rainfall
from app.engines.grid import corner_lonlats, lonlat_bounds, lonlat_to_rowcol, rowcol_to_lonlat
from app.engines.render import DEPTH_COLORS, DEPTH_EDGES, WATER_COLOR, to_png_binned
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
    dist_stream_m: np.ndarray
    bld: dict[str, np.ndarray] | None  # building arrays from buildings_proxy.parquet
    pop_unattr: np.ndarray | None
    dist_road_m: np.ndarray
    shelters: list[dict]
    networks: dict
    mode: str = "auto"  # legacy label only; physics is chosen per cell (engines/profile.py)
    pluvial: dict | None = None  # S13 static depression analysis (every area that has it)
    dem: np.ndarray | None = None
    drain_cands: list[dict] = field(default_factory=list)
    fsi: np.ndarray | None = None
    aoi_mask: np.ndarray | None = None  # cells inside the drawn bbox; the grid adds a 3 km hydrology buffer
    src_cache: dict = field(default_factory=dict)
    bridges: dict | None = None  # {"spans": [...], "links": {mode: {edge row: [span index]}}} (engines/bridges.py)
    hollows_ok: np.ndarray | None = None  # per depression: waterlogs (catchment mostly built-up)
    reach_ok: np.ndarray | None = None  # per reach: river stage meaningful (not tidal, not a stub)
    profile: dict = field(default_factory=dict)
    places: list[dict] | None = None  # OSM settlement names (places.json; None for areas prepared before 18 Oct)
    landmarks: list[dict] = field(default_factory=list)  # named shelters and hospitals, for place labels

    def with_urban_dem(self, surface_dem: np.ndarray) -> "Area":
        """Urban ponding levels use the same DEM the depressions were built from (FABDEM when available)."""
        if self.pluvial is not None:
            self.dem = self.pluvial.get("dem_bare", surface_dem)
        return self  # SRC tables by Manning's n, plus the flow path


_area_locks: dict[str, threading.Lock] = {}
_area_locks_guard = threading.Lock()


def load_area(aoi_id: str) -> Area:
    """Static data of an area, cached per process (4 areas). Concurrent first requests for one area (opening it asks for
    the forecast, the rain hours and the records at once) wait for a single load instead of each loading it."""
    with _area_locks_guard:
        lock = _area_locks.setdefault(aoi_id, threading.Lock())
    with lock:
        return _load_area(aoi_id)


def _opt(fn, *args):
    """fn(*args), or None when the file does not exist (optional layers, older areas)."""
    try:
        return fn(*args)
    except NotFound:
        return None


def _network(aoi_id: str, mode: str):
    e = _opt(storage.load_gdf, aoi_id, f"edges_{mode}.parquet")
    return None if e is None else evac.load_network(e, storage.load_gdf(aoi_id, f"nodes_{mode}.parquet"))


@lru_cache(maxsize=4)
def _load_area(aoi_id: str) -> Area:
    # ~25 independent reads: in parallel (one after another took 6-11 s for the first run of an area on an instance)
    jobs = {
        "reaches": (storage.get_json, "reaches.json"), "h30": (storage.load_layers, "hydro30"),
        "sus": (storage.load_layers, "susceptibility"), "grid": (storage.load_grid,), "terr": (storage.load_layers, "terrain"),
        "hgrid": (storage.get_json, "hydro_grid.json"), "hz": (storage.load_layers, "hazard_hist"),
        "lc": (storage.load_layers, "landcover"), "native": (storage.load_layers, "hydro_native"),
        "hotspots": (storage.get_json, "hotspots.json"), "bld": (_load_buildings,), "pop": (storage.load_layers, "population"),
        "derived": (storage.load_layers, "derived"), "shelters": (storage.get_json, "shelters.json"),
        "medical": (storage.get_json, "medical.json"), "places": (storage.get_json, "places.json"),
        "pluvial": (storage.load_layers, "pluvial"),  # waterlogging layers (all areas prepared since 17 Oct; backfilled)
        "drains": (storage.get_json, "drain_candidates.json"), "bridges": (storage.get_json, "bridges.json"),
        "walk": (_network, "walk"), "drive": (_network, "drive"),
    }
    with ThreadPoolExecutor(12) as ex:
        doc_f = ex.submit(fs.get_aoi, aoi_id)
        futs = {k: ex.submit(_opt, fn, aoi_id, *rest) for k, (fn, *rest) in jobs.items()}
        got = {k: f.result() for k, f in futs.items()}
        doc = doc_f.result() or {}
    if got["reaches"] is None:
        raise AreaNotReady(f"AOI {aoi_id} is not prepared yet")
    h30, terr, grid, sus = got["h30"], got["terr"], got["grid"], got["sus"] or {}
    from app.services import places as pl
    area = Area(
        aoi_id=aoi_id,
        grid=grid,
        hgrid=hy.HydroGrid(**got["hgrid"]),
        hand=h30["hand"],
        perm=flood.permanent_water(got["hz"]["gsw_occ"]),
        reach_id_30=h30["reach_id"],
        lc_class=got["lc"]["lc_class"],
        reaches=got["reaches"],
        native=got["native"],
        hotspots=got["hotspots"],
        slope_deg=terr["slope_deg"],
        dist_stream_m=h30["dist_stream_m"],
        bld=got["bld"],
        pop_unattr=got["pop"].get("pop_unattributed"),
        dist_road_m=got["derived"]["dist_road_m"],
        shelters=got["shelters"] or [],
        networks={m: got[m] for m in ("walk", "drive") if got[m] is not None},
        mode=doc.get("mode", "auto"),
        pluvial=got["pluvial"],
        dem=None,
        drain_cands=(got["drains"] or []) if got["pluvial"] is not None else [],
        fsi=sus.get("fsi"),
        aoi_mask=_bbox_mask(grid, doc.get("bbox")),
        bridges=got["bridges"],
        places=got["places"],
        landmarks=pl.landmarks_from((got["shelters"] or []) + (got["medical"] or [])),
    ).with_urban_dem(terr["dem"])
    area.reach_ok = prof.reliable_reaches(area.reaches, _reach_built_share(area))
    if area.pluvial is not None:
        area.hollows_ok = prof.built_hollows(area.pluvial, area.lc_class)
    area.profile = prof.area_profile(area.slope_deg, area.lc_class, area.aoi_mask, area.reaches, area.hollows_ok, area.reach_ok)
    if (doc.get("meta") or {}).get("profile") != area.profile:
        try:
            fs.update_aoi(aoi_id, {"meta.profile": area.profile})
        except Exception:  # best effort: the profile is recomputed on every load
            pass
    return area


def drain_mm_h(aoi_id: str, value: float | None = None) -> float:
    """Storm-drain capacity under built-up land: the scenario's value, else the area's confirmed one (Gemini lookup with
    sources, confirmed by a person), else the default (25 mm/h, Mumbai's historical design standard)."""
    if value:
        return float(value)
    d = (fs.get_aoi(aoi_id) or {}).get("drain") or {}
    return float(d.get("mm_h") or get_settings().urban_drain_capacity_mm_h)


def _reach_built_share(area: Area) -> np.ndarray:
    """Share of each reach's upstream catchment (inside the hydrology grid) that is built-up (Dynamic World)."""
    hg = area.hgrid
    rows, cols = np.indices((hg.height, hg.width))
    lon = hg.lon0 + (cols.ravel() + 0.5) * hg.cell_deg
    lat = hg.lat0 - (rows.ravel() + 0.5) * hg.cell_deg
    r30, c30 = lonlat_to_rowcol(area.grid, lon, lat)
    inside = (r30 >= 0) & (r30 < area.grid.height) & (c30 >= 0) & (c30 < area.grid.width)
    built = np.zeros(lon.size)
    built[inside] = (np.asarray(area.lc_class)[r30[inside], c30[inside]] == prof.BUILT)
    down = area.native["downstream"].astype(np.int64)
    acc_b, acc_n = hy.accumulate(down, built), hy.accumulate(down, inside.astype(float))
    last = np.array([r["cells"][-1] for r in area.reaches], np.int64)
    return acc_b[last] / np.maximum(acc_n[last], 1)


def _bbox_mask(grid: GridSpec, bbox) -> np.ndarray:
    rr, cc = np.indices((grid.height, grid.width))
    if not bbox:
        return np.ones((grid.height, grid.width), bool)
    lon, lat = (np.asarray(x) for x in rowcol_to_lonlat(grid, rr, cc))
    w, s, e, n = bbox
    return (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)


def _load_buildings(aoi_id: str) -> dict[str, np.ndarray] | None:
    b = _opt(storage.load_gdf, aoi_id, "buildings_proxy.parquet")
    if b is None:
        return None
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
    """C_reach (mean C over hydro cells upstream of the reach end), tc_h and A_loc per reach.

    NOTE(spec-drift): tc uses Kirpich on the DEM longest flow path inside the grid with S = relief / L (Kirpich's own
    definition) instead of Hack's length with the 2 km reach slope; Hack is the fallback for one-cell paths.
    Cached with the area per C table (the inputs never change between runs)."""
    key = ("reach_params", tuple(c_table))
    if key not in area.src_cache:
        area.src_cache[key] = _reach_params(area, c_table)
    return tuple(x.copy() for x in area.src_cache[key])


def _reach_params(area: Area, c_table: list[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
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
    if "flow_path" not in area.src_cache:
        area.src_cache["flow_path"] = hy.flow_path(down, hg, area.native["elv"])
    L, head = area.src_cache["flow_path"]
    z = np.nan_to_num(area.native["elv"].ravel().astype(float))
    return np.clip(C, 0.10, 0.95), rainfall.tc_hours_path(L[last], head[last] - z[last], A_loc), A_loc


def external_inflow(area: Area, total_m3s: float) -> np.ndarray | float:
    """Upstream inflow per reach: the scenario's main-stem flow entering the grid, shared in proportion to each
    reach's upstream area outside the grid (A_up - A_loc), so the main stem carries all of it and mass is conserved
    downstream. Zero for reaches whose whole catchment lies inside the grid."""
    if not total_m3s:
        return 0.0
    ext = np.array([max(0.0, r["A_up_km2"] - r["A_loc_km2"]) for r in area.reaches])
    return total_m3s * ext / ext.max() if ext.max() > 0 else 0.0


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


_obs: dict[tuple, list[float]] = {}


def observed_series(area: Area, day_iso: str, H: int) -> tuple[list[float], str, list[str], str | None]:
    """Actual rain of a past local day from NASA GPM IMERG (~2 days behind): its wettest H hours."""
    from datetime import date as _date, datetime, timedelta
    from app.services import earth_engine as ees
    day = _date.fromisoformat(day_iso)
    key = (area.aoi_id, day.isoformat())
    if key not in _obs:  # Earth Engine data: safe to keep
        lon, lat = area_centroid(area)
        start = (datetime(day.year, day.month, day.day) - timedelta(hours=5, minutes=30)).isoformat() + "Z"  # IST midnight
        _obs[key] = ees.imerg_hourly(lon, lat, start, 24)
    hours = _obs[key]
    series, k = rainfall.wettest_window(hours, H)
    warn = [] if sum(hours) > 0 else ["NASA IMERG shows no rain that day here (or the day is not processed yet; it runs about 2 days behind)"]
    return ([round(float(x), 2) for x in series], f"Observed rain {day.strftime('%a %d %b')} (NASA IMERG, {sum(hours):.0f} mm that day), "
            f"wettest {H} h from {k:02d}:00", warn, f"{day.isoformat()}T{k:02d}:00")


def rain_records(area: Area) -> dict:
    """Yearly wettest days near the area (CHIRPS 2001-2024) and the daily rain expected once in 2, 10, 25 and 100 years
    (Gumbel fit), cached per area: the choices behind "Record" rain."""
    if storage.exists(area.aoi_id, "chirps_annual.json"):
        annual = storage.get_json(area.aoi_id, "chirps_annual.json")["annual"]
    else:
        from app.services import earth_engine as ees
        lon, lat = area_centroid(area)
        annual = ees.chirps_annual_max(lon, lat)
        storage.put_json(area.aoi_id, "chirps_annual.json", {"annual": annual})
    mx = [a["mm"] for a in annual]
    top = max(annual, key=lambda a: a["mm"]) if annual else {"mm": 0.0, "date": None}
    return {"years": [annual[0]["year"], annual[-1]["year"]] if annual else [], "annual": annual,
            "record": {"mm": top["mm"], "date": top.get("date")},
            "levels": [{"T": T, "mm": round(rainfall.return_level_mm(mx, T), 1)} for T in (2, 10, 25, 100)],
            "source": "CHIRPS daily rainfall 2001-2024 (UCSB/CHG, Earth Engine), wettest 5 km cell near the area",
            "method": "Gumbel (EV1) fit to the yearly maxima, method of moments"}


def _reshape(series: list[float], p: ScenarioParams, H: int) -> tuple[list[float], str]:
    """Respread a forecast's or measured day's rain when a shape is chosen (same total)."""
    if p.rain_shape in ("constant", "triangular_front") and H > 1:
        return rainfall.distribute_total(sum(series), H, p.rain_shape), (", spread evenly" if p.rain_shape == "constant" else ", reshaped as an early peak")
    return series, ""


def rain_series(p: ScenarioParams, area: Area) -> tuple[list[float], str, list[str], str | None]:
    """The hourly rain a run uses: the source's series (`base_rain`) times the strength the person chose. Anything other
    than x1 is labelled as not the actual forecast / record, so a brief never passes it off as real data."""
    return with_strength(base_rain(p, area), p)


def with_strength(base: tuple, p: ScenarioParams) -> tuple[list[float], str, list[str], str | None]:
    series, label, warnings, start, what = base
    k = float(p.rain_scale or 1.0)
    if what and abs(k - 1) > 1e-6:
        series = [min(300.0, v * k) for v in series]
        label += f"; x{k:.2f} the {what} (not the actual {what})"
    elif abs(k - 1) > 1e-6 and p.rain_source != RainSource.manual and not p.rain_series_override:
        # the forecast or record failed and fell back to manual rain: say the strength was not applied
        warnings = [*warnings, f"Strength x{k:.2f} not applied: the chosen rain was unavailable, so default rain was used"]
    return series, label, warnings, start


def base_rain(p: ScenarioParams, area: Area) -> tuple[list[float], str, list[str], str | None, str | None]:
    """S10.5: forecast / worst / best / observed / historical_extreme / preset / manual hourly series (mm/h), a human
    label, warnings, the local clock time of hour 1 for real rain (None for hypothetical rain), and what the strength
    slider scales ("forecast", "measured rain", "record", "IMD category"; None for hand edits and your own intensity)."""
    from datetime import date as _date
    from app.services.weather import get_provider
    H, warnings = p.duration_h, []
    src = p.rain_source
    if p.rain_series_override:  # hand-edited hours, or a replay of an observed storm (scripts/event_replay.py)
        # exactly the hours the panel shows (duration_h): extra edited hours beyond it used to run too, so a "4 h" run
        # could simulate 9
        series = [max(0.0, float(v)) for v in p.rain_series_override][:max(1, min(24, H))]
        series += [0.0] * (H - len(series))
        return series, p.preset_label or f"Observed rain, {len(series)} h", warnings, p.override_start_local, None
    if src == RainSource.observed and p.observed_date:
        series, label, warn, start = observed_series(area, p.observed_date, H)
        series, how = _reshape(series, p, H)
        return series, label + how, warn, start, "measured rain"
    if src in (RainSource.forecast, RainSource.worst, RainSource.best):
        try:
            lon, lat = area_centroid(area)
            prov = get_provider()
            daily, hourly = prov.daily(lat, lon, 10), prov.hourly(lat, lon, 240)
            k = p.forecast_day_index if p.forecast_day_index is not None else rainfall.worst_day_index(daily, hourly)
            day = daily[min(k, len(daily) - 1)]["date"]
            first = rainfall.first_covered_hour(hourly, day)  # never a window in hours already past
            series, start = rainfall.wettest_window(rainfall.day_hours(hourly, day)[first:], H)
            start += first
            mult = {RainSource.worst: p.worst_multiplier, RainSource.best: p.best_multiplier}.get(src, 1.0)
            series = [v * mult for v in series]
            label = f"Forecast {_date.fromisoformat(day).strftime('%a %d %b')}, wettest {H} h from {start:02d}:00"
            if src != RainSource.forecast:
                label += f", {src.value} case x{mult:g}"
            if sum(series) == 0:
                warnings.append("The forecast shows no rain for this window; try record or custom rain")
            series, how = _reshape(series, p, H)
            return series, label + how, warnings, f"{day}T{start:02d}:00", "forecast"
        except Exception as e:  # provider down or no key: fall back, never fail the run
            warnings.append(f"Forecast unavailable ({e.__class__.__name__}); used manual rain instead")
    shape = p.rain_shape if p.rain_shape in ("constant", "triangular_front") else None
    if src == RainSource.historical_extreme:
        try:
            T = p.return_period_y
            if T:
                rec = rain_records(area)
                mm = next(lv["mm"] for lv in rec["levels"] if lv["T"] == T)
                head = f"1-in-{T}-year rain"
                what = f"a 1-in-{T}-year day here ({mm:.0f} mm, Gumbel fit to CHIRPS yearly maxima 2001-2024{', an estimate' if T > 50 else ''})"
            else:
                mm = historical_max_mm(area)
                head, what = "Record rain", f"the wettest day on record nearby ({mm:.0f} mm, CHIRPS 2001-2024)"
            # NOTE(spec-drift): the spec spread the whole daily maximum over H hours (201 mm in 4 h = 50 mm/h);
            # the wettest H hours of that day follow the IMD reduction formula P_H = P_24 (H/24)^(1/3).
            depth = rainfall.daily_to_duration_mm(mm, H)
            series = rainfall.distribute_total(depth, H, shape or p.hyetograph)
            return series, (f"{head}: {depth:.0f} mm in {H} h, the wettest hours of {what}, IMD reduction rule"), warnings, None, "record"
        except Exception as e:
            warnings.append(f"Historical extreme unavailable ({e.__class__.__name__}); used manual rain instead")
    if p.rain_preset:
        series, label = rainfall.preset_series(p.rain_preset, H, p.hyetograph, shape)
        return series, label, warnings, None, "IMD category"
    series = rainfall.manual_series(p.manual_intensity_mm_h, H, shape or p.hyetograph)
    how = (shape or p.hyetograph).replace("triangular_front", "early peak").replace("constant", "steady")
    label = p.preset_label or f"Your own rain: {p.manual_intensity_mm_h:g} mm/h on average for {H} h ({how})"
    return series, label, warnings, None, None


def screening(area: Area, daily: list[dict], hourly: list[dict], duration_h: int) -> list[dict]:
    """S10.6: per forecast day, one-reach (largest A_loc) envelope on the wettest window -> badge."""
    cfg = get_settings()
    # both hazards on every area: the river (largest reliable reach) and street waterlogging (peak hour vs drain
    # capacity, where the area has built-up hollows); the badge is the higher of the two
    ok = area.reach_ok if area.reach_ok is not None else np.ones(len(area.reaches), bool)
    river = bool(ok.any())
    pond = area.hollows_ok is not None and bool(area.hollows_ok.any())
    if river:
        C, tc_h, A_loc = reach_params(area, cfg.runoff_c)
        r = int(np.argmax(np.where(ok, A_loc, -1)))
        src = [get_src(area, get_settings().manning_n)[r]]
    rank = {"low": 0, "elevated": 1, "high": 2}
    dc = drain_mm_h(area.aoi_id) if pond else 0.0  # one Firestore read, not one per forecast day
    out = []
    for d in daily:
        win, _ = rainfall.wettest_window(rainfall.day_hours(hourly, d["date"]), duration_h)
        peak = max(win) if win else 0.0
        stage, badge = 0.0, "low"
        if river:
            h, _ = flood.hourly_envelope(win, tc_h[r:r + 1], C[r:r + 1], A_loc[r:r + 1], src, arf=get_settings().apply_arf)
            stage = float(h.max())
            badge = "high" if stage >= 3 else "elevated" if stage >= 1 else "low"
        if pond:
            b2 = "high" if peak >= 2 * dc else "elevated" if peak >= dc else "low"
            badge = max(badge, b2, key=rank.get)
        out.append({"date": d["date"], "precip_mm": d["precip_mm"], "max_stage_m": round(stage, 2), "peak_mm_h": round(peak, 1), "badge": badge})
    return out


CORRIDOR_HAND_M = 3.0  # within this height of a reliable river channel, flow-model water is the river (moving water)


class _SkipFlow(Exception):
    pass


def run_pipeline(p: ScenarioParams, flow_model: bool = True) -> RunResult:
    """`flow_model=False` (quick previews): river and hollow water only, no 2D flow model, labelled as such."""
    t0 = time.time()
    timings: dict[str, float] = {}
    area = load_area(p.aoi_id)
    run_id = uuid.uuid4().hex[:12]

    cfg = get_settings()
    rain, rain_label, warnings, start_local = rain_series(p, area)
    C, tc_h, A_loc = reach_params(area, cfg.runoff_c)
    h, _Q = flood.hourly_envelope(rain, tc_h, C, A_loc, get_src(area, p.manning_n), p.river_offset_m,
                                  inflow_m3s=external_inflow(area, p.upstream_inflow_m3s), arf=cfg.apply_arf)
    # river stage only on reliable channels (engines/profile.py): tidal channels and one-cell stubs have no meaningful
    # rating curve (Mumbai's Mahim outlet hit the 30 m cap and flooded 14% of the area); nor has a reach that hits the cap
    ok = (area.reach_ok if area.reach_ok is not None else np.ones(len(area.reaches), bool)).copy()
    capped = np.any(h >= hy.SRC_STAGES[-1] + p.river_offset_m - 1e-6, axis=1)
    if (capped & ok).any():
        warnings.append(f"{int((capped & ok).sum())} channel(s) reached the top of their rating curve (30 m); river flooding "
                        "along them is left out of this run")
    ok &= ~capped
    if (~ok).any() and area.profile.get("tidal"):
        warnings.append("Tidal channels near sea level are not modelled for river flooding (their level follows the sea); "
                        "tides and storm surge are not included")
    h = np.where(ok[:, None], h, 0.0)
    rid = np.where(area.reach_id_30 >= 0, area.reach_id_30, 0)
    reach_30 = np.where((area.reach_id_30 >= 0) & ok[rid], area.reach_id_30, -1)
    depth = flood.depth_stack(h, reach_30, area.hand, area.perm)
    river_only = np.nan_to_num(depth)
    pond_fill, still = None, None
    drain = drain_mm_h(area.aoi_id, p.drain_capacity_mm_h)
    if area.pluvial is not None:
        # waterlogging in built-up hollows above the storm-drain capacity; the flood depth is the deeper of the two
        pond, pond_fill = pluvial.ponding(area.pluvial, area.dem, rain, area.grid.cell, drain,
                                          use=area.hollows_ok)
        river_d = np.nan_to_num(depth)
        still = pond.max(axis=0) > river_d.max(axis=0)  # standing water (still-water hazard thresholds in evac)
        depth = np.where(area.perm[None], np.nan, np.maximum(river_d, pond)).astype(np.float32)
        if area.hollows_ok is not None and area.hollows_ok.any() and not pond.any():
            warnings.append(f"Rain stays within the storm-drain capacity ({drain:g} mm/h); no street waterlogging estimated")
    timings["flood"] = round(time.time() - t0, 2)
    # the 2D flow model, hour by hour, in every run (17 Oct): the HAND and hollow models above only hold water in river
    # corridors and closed hollows, so rain the drains cannot carry, spreading over flat streets, was counted nowhere
    # (Kalyan, 2150 mm in 9 h: 0.026 km2 and 8 people vs 1.64 km2 and ~15,000 people in water in the flow model). The
    # depth is now the deepest of the three in each cell; the same simulation is stored as the run's 3D water.
    static_depth = depth.copy()  # river + hollows alone: kept for the 3D comparison view and the agreement check
    sim, static_last = None, np.nan_to_num(depth[-1]).copy()
    tf = time.time()
    try:
        from app.pipeline import flow as flowmod
        if not flow_model:
            raise _SkipFlow()
        sim = flowmod.simulate(area, rain, p.model_dump(mode="json"))
        fd = flowmod.hourly_depth(sim, len(rain))
        # flooding = water at least 15 cm deep, or at least 5 cm on near-flat ground (< 5 deg). Thinner water on slopes
        # is rain running off down the hillside (Rudraprayag: 1.1 km2 of 6-25 cm films on 14 deg slopes counted as
        # flood at the plain 5 cm cut); flat cities are unchanged by this rule (Kalyan, Kurla, Amingaon within 1 %)
        flat_ = np.nan_to_num(area.slope_deg, nan=90.0) < 5.0
        fd = np.where((fd >= 0.15) | ((fd >= 0.05) & flat_[None]), fd, 0.0)
        base = np.nan_to_num(depth)
        # standing water for the evacuation thresholds: hollows deeper than the river, and flow-model water deeper than
        # the river OFF the river corridors. In a reliable river's corridor (the river model wets it, or it is within 3 m
        # of the channel) flow-model water is the river itself, moving, so it keeps the moving-water thresholds
        rmax = river_only.max(axis=0)
        corridor = (reach_30 >= 0) & ((rmax > 0) | (np.nan_to_num(area.hand, nan=99.0) < CORRIDOR_HAND_M))
        held = still if still is not None else np.zeros(rmax.shape, bool)
        still = held | ((fd.max(axis=0) > rmax) & ~corridor)
        depth = np.where(area.perm[None], np.nan, np.maximum(base, fd)).astype(np.float32)
    except _SkipFlow:
        warnings.append("Quick preview: river and hollow water only; water spreading over streets (flow model) is not "
                        "included. Run the scenario for the full model")
    except Exception as e:  # never fail a run on it: the river and hollow maps stand alone
        log.exception("flow model in run failed")
        warnings.append(f"Flow model unavailable this run ({e.__class__.__name__}); water spreading over streets is not included")
    timings["flow_model"] = round(time.time() - tf, 2)

    methods = {
        "runoff": "rational method, C by land cover, A = local catchment area"
                  + (", TP-29 areal reduction (Leclerc & Schaake 1972)" if cfg.apply_arf else ""),
        "tc": "Kirpich (1940) on the DEM longest flow path, S = relief / length",
        "stage": "HAND synthetic rating curves (Zheng et al. 2018), worst-case envelope (no recession)",
        "damage": "JRC global depth-damage curve, Asia residential (Huizinga et al. 2017)",
    }
    t2 = time.time()
    exposure, triage_rows, queue, ctx = _exposure(area, p, depth, warnings)
    timings["exposure"] = round(time.time() - t2, 2)

    drains_out, pond_img = [], None
    if pond_fill is not None:
        drains_out = _drains(area, depth, pond_fill, ctx)
        lab = area.pluvial["dep_label"]
        pond_img = np.where(lab > 0, pond_fill[-1][lab], np.nan)  # drawn with the hourly maps below
        methods["urban"] = (f"Priority-Flood depressions (Barnes et al. 2014) filled to level by rain above the "
                            f"{drain:g} mm/h drain capacity, in hollows whose catchment is at least "
                            f"{int(prof.BUILT_HOLLOW * 100)}% built-up; screening, not hydrodynamics")
    methods["compound"] = ("Depth = the deepest of river flooding (HAND, reliable non-tidal channels), street "
                           "waterlogging in hollows, and the 2D shallow-water flow model (rain, drains and river inflow "
                           "moving over the ground) in each cell, worst so far at each hour; physics chosen per cell from "
                           "the data, no area mode" if sim is not None else
                           "Depth = the deeper of river flooding (HAND, reliable non-tidal channels) and street "
                           "waterlogging in each cell (flow model unavailable this run)")

    t3 = time.time()
    # bridges close on river stage at the deck (reliable channels only) or on flooded approaches
    if ctx:  # depth at which people are in danger, per cell: FD2321 hazard rating, moving river vs standing water
        ctx["evac_depth"] = prof.evac_depths(area.reaches, reach_30, still, p.manning_n)
    ev = evac.plan(area, p, depth, h, ctx, warnings) if ctx else {}
    timings["routing"] = round(time.time() - t3, 2)

    t1 = time.time()
    pngs = [f"depth_h{t + 1}" for t in range(depth.shape[0])] + (["ponding"] if pond_img is not None else [])

    def png(name: str) -> None:  # drawn and uploaded in the pool: drawing releases the GIL (24 maps in turn took seconds)
        img = to_png_binned(pond_img, [0.01, 0.3, 0.7], ["#9ecae1", "#3182bd", "#08306b"]) if name == "ponding" else \
            to_png_binned(depth[int(name[7:]) - 1], DEPTH_EDGES, DEPTH_COLORS, nan_color=WATER_COLOR)
        storage.put_run(run_id, f"png/{name}.png", img, "image/png")

    def npz(name: str, d: np.ndarray) -> None:
        buf = io.BytesIO()
        np.savez_compressed(buf, depth=d.astype(np.float16))
        storage.put_run(run_id, name, buf.getvalue())

    with ThreadPoolExecutor(8) as ex:
        jobs = [ex.submit(png, k) for k in pngs]
        jobs.append(ex.submit(npz, "depth.npz", depth))
        if sim is not None:  # river + hollows alone, for the 3D comparison and the flow agreement check
            jobs.append(ex.submit(npz, "static_depth.npz", static_depth))
        jobs.append(ex.submit(storage.put_run, run_id, "verification.json", json.dumps(queue).encode(), "application/json"))
        if ctx:  # per-building risk (0 critical .. 3 low) for the 3D view
            rb = io.BytesIO()
            np.save(rb, ctx["risk_codes"])
            jobs.append(ex.submit(storage.put_run, run_id, "bld_risk.npy", rb.getvalue()))
        for k in ("roads", "routes"):
            if ev.get(f"{k}_geojson"):
                jobs.append(ex.submit(storage.put_run, run_id, f"{k}.geojson", ev[f"{k}_geojson"].encode(),
                                      "application/geo+json"))
        for j in jobs:
            j.result()
    if sim is not None:  # the run's 3D water, uploaded in the background (frames are MBs) so 3D does not simulate again
        flowmod.store_later(run_id, area, sim, static_last)
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
        flooded_area_km2_by_hour=[round(flood.flooded_area_km2(np.where(area.aoi_mask, depth[t], 0), area.grid.cell), 3)
                                  for t in range(len(rain))],
        depth_png_urls=[f"/api/runs/{run_id}/layers/{k}.png" for k in pngs if k.startswith("depth_")],
        overlay_bounds=lonlat_bounds(area.grid), overlay_corners=corner_lonlats(area.grid),
        hotspots=hotspots, warnings=warnings, exposure=exposure, triage=triage_rows,
        shelters=ev.get("shelters", []), bridges=ev.get("bridges", []),
        capacity_gap_people=ev.get("capacity_gap_people", 0), assembly_points=ev.get("assembly_points", []),
        staging_points=ev.get("staging_points", []), routes=ev.get("routes_summary", []),
        people_to_evacuate=ev.get("people_to_evacuate", 0),
        roads_geojson_url=f"/api/runs/{run_id}/files/roads.geojson" if ev else "",
        drains=drains_out, ponding_png_url=f"/api/runs/{run_id}/layers/ponding.png" if pond_img is not None else "",
        routes_geojson_url=f"/api/runs/{run_id}/files/routes.geojson" if ev else "",
        start_local=start_local, evac_window_h=_evac_window(ev),
        demand_breakdown=ev.get("demand_breakdown", {}), demand_range=ev.get("demand_range", []),
        gap_range=ev.get("gap_range", []),
    )
    _label_places(area, result)
    timings["total"] = round(time.time() - t0, 2)
    result.timings_s = timings
    result.methods = methods
    fs.set_doc("runs", run_id, result.model_dump(mode="json"))
    fs.update_aoi(p.aoi_id, {"latest_run_id": run_id})
    log.info("run %s: %s", run_id, timings)
    return result


def _evac_window(ev: dict) -> int | None:
    """First hour an evacuation route stops being passable, else the first bridge closure: the 'move before' hour."""
    hrs = [r["passable_until_h"] for r in ev.get("routes_summary", []) if r.get("passable_until_h")]
    if not hrs:  # bridges the storm closes; ones OpenStreetMap marks as not open were never usable
        hrs = [b["first_closed_hour"] for b in ev.get("bridges", []) if b.get("first_closed_hour") and b.get("reason") not in ("construction", "closed", "disused")]
    return int(min(hrs)) if hrs else None


def _label_places(area: Area, result: RunResult) -> None:
    """Nearest OSM settlement for clusters, staging and assembly points, bridges and routes (best effort)."""
    try:
        from app.services import places
        # loaded with the area (6 storage reads per run before); older areas without places.json fetch them meanwhile
        pl = area.places if area.places is not None else places.area_places(area.aoi_id, area.grid)
        lm = area.landmarks
    except Exception as e:
        log.info("place labels unavailable: %s", e)
        return
    if not pl:
        return
    for c in result.exposure.clusters:
        c["place"] = places.label(pl, *c["centroid"], landmarks=lm)
        c["place_hi"] = places.label(pl, *c["centroid"], hindi=True, landmarks=lm)
    for coll in (result.staging_points, result.assembly_points, result.routes):
        for x in coll:
            lon, lat = (x.get("lon"), x.get("lat")) if "lon" in x else (x.get("from_lon"), x.get("from_lat"))
            if lon is not None:
                x["place"] = places.label(pl, lon, lat, landmarks=lm)
    for b in result.bridges:
        b.place = places.label(pl, b.lon, b.lat)  # BridgeStatus/ShelterResult allow extra fields
    for s in result.shelters:
        s.place = places.label(pl, s.lon, s.lat)


def _exposure(area: Area, p: ScenarioParams, depth: np.ndarray, warnings: list[str]) -> tuple[ExposureSummary, list[TriageRow], list[dict], dict]:
    """S6.4-S6.9 at run time: scaled population, per-hour exposure, risk at the worst hour, triage, clusters, queue."""
    if area.bld is None or area.pop_unattr is None:
        warnings.append("Buildings not prepared for this area; exposure unavailable")
        return ExposureSummary(), [], [], {}
    b = area.bld
    base_total = float(b["pop_base"].sum() + (area.pop_unattr * area.aoi_mask).sum())
    k = population.scale_factor(base_total, p.pop_multiplier, p.pop_total_override)
    # exposure counts only people inside the drawn area (the 3 km buffer is for hydrology, and has no buildings)
    pop_b, pop_un = b["pop_base"] * k, area.pop_unattr * area.aoi_mask * k
    if p.visitors > 0:  # pilgrims/tourists: spread over the crowding index inside the drawn area (S9 attractors)
        try:
            crowd = np.nan_to_num(storage.load_layers(area.aoi_id, "crowding")["crowd"]) * area.aoi_mask
            if crowd.sum() > 0:
                pop_un = pop_un + p.visitors * crowd / crowd.sum()
                warnings.append(f"{p.visitors:,} visitors added where the crowding index is high (temples, markets, hotels)")
        except Exception as e:
            warnings.append(f"Visitors not added: crowding layer unavailable ({e.__class__.__name__})")
    share = float(b["pop_base"].sum()) / base_total if base_total else 0.0
    if share < 0.5:
        warnings.append(f"Only {share:.0%} of residents could be placed in mapped buildings (Open Buildings coverage); "
                        "the rest are counted from the population grid")
    rows = np.clip(b["row"].astype(int), 0, area.grid.height - 1)
    cols = np.clip(b["col"].astype(int), 0, area.grid.width - 1)
    ph = ex_engine.per_hour(depth, rows, cols, pop_b, pop_un)
    d_w = ph["d_b"][-1]  # worst case: flood depth peaks at the last hour (envelope)
    # S6.3: accepted field photos replace the proxy class and fragility (copies; the cached area stays untouched)
    struct, frag, conf = b["structure_class"].astype(object).copy(), b["fragility"].astype(float).copy(), b["confidence"].astype(float).copy()
    from app.api.photos import building_overrides
    ov = building_overrides(area.aoi_id)
    if ov:
        from app.engines.buildings import apply_field_overrides
        src = apply_field_overrides([str(x) for x in b["bid"]], struct, frag, conf, ov)
        n = int((src == "field_photo").sum())
        if n:
            warnings.append(f"{n} building(s) use field-photo verified classes")
    R, risk, _reason = ex_engine.building_risk(d_w, frag, area.dist_stream_m[rows, cols])
    exposed = d_w >= ex_engine.WET_M
    to_ll = lambda r, c: rowcol_to_lonlat(area.grid, r, c)  # noqa: E731
    cl = ex_engine.clusters(rows, cols, pop_b, R, risk, struct, d_w, exposed, depth[-1], pop_un,
                            block=10, to_lonlat=to_ll, dist_stream_m=area.dist_stream_m)
    summary = ExposureSummary(
        total_pop=int(round(pop_b.sum() + pop_un.sum())),
        exposed_pop_by_hour=ph["exposed_pop_by_hour"],
        exposed_by_depth_band=ph["exposed_by_depth_band"],
        buildings_by_risk={c: int(np.count_nonzero(risk == c)) for c in ex_engine.RISK_ORDER},
        clusters=cl,
    )
    tri = [TriageRow(**r) for r in ex_engine.triage(struct, risk, pop_b)]
    queue = ex_engine.verification_queue(b["bid"], R, conf, pop_b, b["lon"], b["lat"], struct)
    ctx = {"rows": rows, "cols": cols, "pop_b": pop_b, "pop_un": pop_un, "d_b": ph["d_b"],
           "risk_codes": np.array([ex_engine.RISK_ORDER.index(r) for r in risk], np.uint8), "frag": frag,
           "clusters": cl}
    return summary, tri, queue, ctx


def _drains(area: Area, depth: np.ndarray, pond_fill: np.ndarray, ctx: dict) -> list[dict]:
    """S13.4: rank drain/culvert candidates by accumulation, ponding/FSI and exposed people within 300 m."""
    if not area.drain_cands:
        return []
    shape = (area.grid.height, area.grid.width)
    wet = np.nan_to_num(depth[-1]) >= ex_engine.WET_M
    exposed = np.zeros(shape)
    if ctx:
        exposed += np.where(wet, ctx["pop_un"], 0.0)
        m = ctx["d_b"][-1] >= ex_engine.WET_M
        np.add.at(exposed, (ctx["rows"][m], ctx["cols"][m]), ctx["pop_b"][m])
    lab = area.pluvial["dep_label"]
    like = np.where(lab > 0, pond_fill[-1][lab], 0.0)
    cond: dict[str, str] = {}
    try:
        for d in sorted(fs.query("photos", aoi_id=area.aoi_id, kind="drain", accepted=True), key=lambda d: d.get("created_at", "")):
            cond[str(d["linked_drain_id"])] = d["result"]["condition"]
    except Exception as e:
        log.info("drain photos unavailable: %s", e)
    cands = [c for c in area.drain_cands if area.aoi_mask[c["row"], c["col"]]]
    if not cands:
        return []
    rows = [c["row"] for c in cands]
    cols = [c["col"] for c in cands]
    fsi = area.fsi if area.fsi is not None else np.zeros(shape)
    out = drn.priority(cands, rows, cols, area.pluvial["acc_cells"], fsi, like, exposed, cond, area.grid.cell)
    return [{k: v for k, v in d.items() if k not in ("x", "y", "row", "col")} for d in out]
