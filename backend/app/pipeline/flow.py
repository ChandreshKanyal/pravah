"""Background job: the 2D shallow-water flow model (engines/swe.py) for a stored run, for the 3D water animation and as
an independent check of the HAND map. The brief and the 2D map stay on the HAND envelope.

Inputs are the run's own: its hourly rain, the runoff coefficient C by land cover (rational-method losses), the
TP-29 areal reduction when enabled (river mode), the storm-drain capacity (urban mode), and river inflow where reaches
enter the grid (the scenario's upstream flow, shared by outside catchment area, plus the discharge that raises each
entering reach by the scenario's river level, read off its rating curve).
"""
import io
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np

from app.config import get_settings
from app.engines import rainfall, swe
from app.engines.grid import lonlat_to_rowcol
from app.services import firestore as fs, storage

FRAME_S = 300  # one frame every 5 model minutes (10 for storms over 6 h)
TAIL_H = 2  # the model keeps running this long after the rain stops: water from uphill still arrives (peaks often come late)
COLL = "flows"
log = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(1)  # one model at a time: it uses every core
_jobs: dict[str, object] = {}
# every simulation takes this lock, the 3D jobs on _pool and the ones inside runs (run_pipeline) alike: one model at a
# time per instance, as before runs started using it
_model_lock = threading.Lock()
_pending_store: dict[str, tuple[str, object]] = {}  # area -> (run_id, future) of an upload not started yet
_progress: dict[str, float] = {}

MODEL = ("2D shallow-water equations, finite volume (HLL Riemann solver, hydrostatic reconstruction of Chen & Noelle "
         "2017, implicit Manning friction), rain on the grid and river inflow, 30 m cells, adaptive time step")


MAIN_RIVER_KM2 = 100.0  # "river level above normal" adds flow only on rivers bringing at least this much outside catchment


def entry_sources(area, params: dict, cell: float) -> list[dict]:
    """Inflow cells and discharge where outside water enters the grid: a reach whose catchment outside the grid is not
    already carried by the reaches flowing into it. The scenario's upstream flow is shared by that new outside area;
    the river level above normal adds, on main rivers, the discharge that lifts the river by that much on its synthetic
    rating curves (median of the first three reaches)."""
    from app.pipeline.run_pipeline import get_src
    total = float(params.get("upstream_inflow_m3s") or 0.0)
    off = float(params.get("river_offset_m") or 0.0)
    if total <= 0 and off <= 0:
        return []
    reaches = area.reaches
    ext = np.array([max(0.0, r["A_up_km2"] - r["A_loc_km2"]) for r in reaches])
    owner = {c: i for i, r in enumerate(reaches) for c in r["cells"]}
    down = area.native["downstream"]
    carried = np.zeros(len(reaches))
    for i, r in enumerate(reaches):
        j = owner.get(int(down[r["cells"][-1]]))
        if j is not None and j != i:
            carried[j] += ext[i]
    new_ext = np.maximum(ext - carried, 0.0)
    entries = [i for i in range(len(reaches)) if new_ext[i] > 1.0]
    if not entries:
        return []
    src = get_src(area, params.get("manning_n") or get_settings().manning_n)
    hg, grid = area.hgrid, area.grid
    H = len(params.get("_rain", [])) or 1
    out = []
    share = new_ext[entries] / new_ext[entries].sum()
    for k, i in enumerate(entries):
        q = total * float(share[k])
        if off > 0 and new_ext[i] >= MAIN_RIVER_KM2:
            # median over the first three reaches of the river: a head reach mostly outside the grid has a degenerate curve
            chain, j = [], i
            while j is not None and j not in chain and len(chain) < 3:
                chain.append(j)
                j = owner.get(int(down[reaches[j]["cells"][-1]]))
            q += float(np.median([np.interp(off, np.asarray(src[j]["h"], float), np.asarray(src[j]["Q"], float)) for j in chain]))
        rows, cols = [], []
        for r30, c30 in _first_inside(reaches, i, owner, down, hg, grid):  # reach heads can lie in the hydrology margin
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if 0 <= r30 + dr < grid.height and 0 <= c30 + dc < grid.width:
                        rows.append(r30 + dr)
                        cols.append(c30 + dc)
        cells = sorted(set(zip(rows, cols)))
        if cells and q > 0.05:
            out.append({"reach_id": reaches[i]["reach_id"], "rows": [a for a, _ in cells], "cols": [b for _, b in cells],
                        "q": [round(q, 1)] * H, "outside_km2": round(float(new_ext[i]))})
    return out


def _first_inside(reaches, i, owner, down, hg, grid, n=2) -> list[tuple[int, int]]:
    """The first `n` cells of reach i (following it downstream into the next reaches) inside the analysis grid."""
    out, seen = [], set()
    while i is not None and i not in seen and len(out) < n:
        seen.add(i)
        for c in reaches[i]["cells"]:
            rr, cc = divmod(int(c), hg.width)
            lon, lat = hg.lon0 + (cc + 0.5) * hg.cell_deg, hg.lat0 - (rr + 0.5) * hg.cell_deg
            r30, c30 = (int(v) for v in lonlat_to_rowcol(grid, lon, lat))
            if 0 <= r30 < grid.height and 0 <= c30 < grid.width:
                out.append((r30, c30))
                if len(out) == n:
                    break
        i = owner.get(int(down[reaches[i]["cells"][-1]]))
    return out


def _status(run_id: str, **fields) -> None:
    """Progress writes are best effort (a slow Firestore must not kill a finished model run); final states retry."""
    final = fields.get("state") in ("ready", "failed")
    for attempt in range(4 if final else 1):
        try:
            fs.merge_doc(COLL, run_id, {**fields, "updated_at": datetime.now(timezone.utc).isoformat()})
            return
        except Exception as e:  # noqa: BLE001
            log.warning("flow %s: status write failed (%s)", run_id, e)
            if final:
                time.sleep(2 * (attempt + 1))


def _drain_mm_h(aoi_id: str, value) -> float:
    from app.pipeline.run_pipeline import drain_mm_h
    return drain_mm_h(aoi_id, value)


def model_setup(area, rain: list[float], params: dict, force_k: int | None = None) -> dict:
    """Everything the flow model needs for a scenario on an area: ground (conditioned bare earth, coarsened to 60 m
    when cells x hours exceed the budget), runoff C and Manning n by land cover, rain after areal reduction (river
    mode), storm-drain capacity (urban mode) and river inflow sources on the model grid."""
    from app.services.terrain import bare_dem, flow_ground
    cfg = get_settings()
    grid = area.grid
    dem, ground = flow_ground(area.aoi_id)
    k = force_k or (2 if grid.width * grid.height * len(rain) > cfg.flow_max_cell_hours else 1)
    urban = bool(area.profile.get("urban")) if area.profile else area.pluvial is not None
    arf = 1.0  # TP-29 areal reduction by area size (close to 1 for a few km2), for every area
    if cfg.apply_arf and area.aoi_mask is not None:
        arf = float(rainfall.areal_reduction_factor(area.aoi_mask.sum() * grid.cell**2 / 1e6, len(rain)))
    C = rainfall.runoff_c(area.lc_class, cfg.runoff_c)
    lc = np.asarray(area.lc_class)
    lut = np.asarray(swe.MANNING_DW)
    n = np.where((lc >= 0) & (lc < len(lut)), lut[np.clip(lc, 0, len(lut) - 1)], cfg.manning_n)
    sources = entry_sources(area, {**params, "_rain": rain}, grid.cell)
    for s_ in sources:  # inflow cells on the model grid
        cells = sorted({(r // k, c // k) for r, c in zip(s_["rows"], s_["cols"])})
        s_["rows"], s_["cols"] = [a for a, _ in cells], [b for _, b in cells]
    zc = swe.coarsen(dem, k)
    if k > 1 and ground.get("conditioned"):  # carve again at the model resolution (averaging re-blocks narrow cuts)
        zc = swe.condition(swe.coarsen(bare_dem(area.aoi_id)[0], k))[0].astype(np.float64)
    return {"k": k, "dem": dem, "ground": ground, "z": zc, "C": swe.coarsen(np.nan_to_num(C, nan=0.5), k), "n": swe.coarsen(n, k),
            # storm drains only under built-up cells; elsewhere rain soaks in through the runoff coefficient
            "rain": [x * arf for x in rain], "drain": swe.coarsen((lc == 6) * _drain_mm_h(area.aoi_id, params.get("drain_capacity_mm_h")), k), "sources": sources,
            "drain_mm_h": _drain_mm_h(area.aoi_id, params.get("drain_capacity_mm_h")),
            "arf": arf, "urban": urban}


def run_maxima(area, rain: list[float], params: dict, force_k: int | None = None) -> np.ndarray:
    """Peak depth (m) on the analysis grid for a scenario, without storing anything (emulator training)."""
    m = model_setup(area, rain, params, force_k)
    res = swe.simulate(m["z"], area.grid.cell * m["k"], m["C"], m["n"], m["rain"], m["drain"], m["sources"], 3600, tail_h=TAIL_H)
    if m["k"] == 1:
        return res.hmax.astype(np.float32)
    z0 = np.zeros_like(res.hmax)
    peak = swe.encode_frame(res.hmax, z0, z0)  # the tracked maximum, filled into 30 m cells from the lowest up
    return swe.decode_depth(swe.downscale_frame(peak, np.asarray(m["dem"], np.float64), m["k"])[0]).astype(np.float32)


def simulate(area, rain: list[float], params: dict, progress=None) -> dict:
    """Run the flow model for a scenario on an area (nothing stored): frames on the analysis grid and maxima."""
    with _model_lock:
        return _simulate(area, rain, params, progress)


def _simulate(area, rain: list[float], params: dict, progress=None) -> dict:
    t0 = time.time()
    grid = area.grid
    m = model_setup(area, rain, params)
    k, dem = m["k"], m["dem"]
    frame_s = FRAME_S if len(rain) <= 6 else 2 * FRAME_S
    res = swe.simulate(m["z"], grid.cell * k, m["C"], m["n"], m["rain"], m["drain"], m["sources"], frame_s, progress, tail_h=TAIL_H)
    z30 = np.asarray(dem, np.float64)
    frames = np.stack([swe.downscale_frame(f, z30, k) for f in res.frames])  # [F, 3, rows, cols] uint8
    if k > 1:  # maxima on the analysis grid: depth from the downscaled frames, the rest repeated from the model cells
        rep = lambda a: np.repeat(np.repeat(a, k, 0), k, 1)[:grid.height, :grid.width]  # noqa: E731
        res.hmax = swe.decode_depth(frames[:, 0].max(axis=0))
        res.vmax, res.hazard, res.t_arrival_s = rep(res.vmax), rep(res.hazard), rep(res.t_arrival_s)
    return {"res": res, "frames": frames, "frame_s": frame_s, "m": m, "t0": t0}


def hourly_depth(sim: dict, hours: int) -> np.ndarray:
    """Deepest water so far at the end of each rain hour (m) [H, rows, cols], from the frames: the same "worst so far"
    meaning as the hourly map, so the map, people and roads read the flow model hour by hour."""
    f = sim["frames"][:, 0]
    per_h = 3600 // sim["frame_s"]
    out = np.zeros((hours,) + f.shape[1:], np.float32)
    run = np.zeros(f.shape[1:], np.uint8)
    for h in range(hours):
        run = np.maximum(run, f[min(len(f) - 1, h * per_h + 1):min(len(f), (h + 1) * per_h + 1)].max(axis=0, initial=0))
        out[h] = swe.decode_depth(run)
    return out


def store(run_id: str, area, sim: dict, static_depth: np.ndarray | None = None) -> dict:
    """Save a simulation as the run's flow result (frames for 3D, maxima, summary in Firestore)."""
    res, frames, frame_s, m, t0 = sim["res"], sim["frames"], sim["frame_s"], sim["m"], sim["t0"]
    grid = area.grid
    storage.put_run_gz(run_id, "flow/frames.bin", frames.tobytes())
    buf = io.BytesIO()
    np.savez_compressed(buf, hmax=res.hmax.astype(np.float16), vmax=res.vmax.astype(np.float16),
                        hazard=res.hazard.astype(np.float16), t_arrival_s=res.t_arrival_s)
    storage.put_run(run_id, "flow/summary.npz", buf.getvalue())

    aoi = area.aoi_mask if area.aoi_mask is not None else np.ones(res.hmax.shape, bool)
    perm = np.asarray(area.perm, bool)
    a_km2 = grid.cell**2 / 1e6
    wet = (res.hmax >= swe.H_WET) & aoi & ~perm
    hz = res.hazard
    hazard_km2 = {name: round(float(((hz >= lo) & (hz < hi) & wet).sum() * a_km2), 3)
                  for name, lo, hi in (("low", 0, 0.75), ("some", 0.75, 1.25), ("most", 1.25, 2.0), ("all", 2.0, np.inf))}
    cmp = {}
    try:  # agreement with the river + waterlogging (HAND) map at its worst hour (both are maxima over the storm)
        d = static_depth if static_depth is not None else _static_depth(run_id)[-1]
        hand = (np.nan_to_num(d) >= swe.H_WET) & aoi & ~perm
        inter, union = int((wet & hand).sum()), int((wet | hand).sum())
        cmp = {"hand_km2": round(float(hand.sum() * a_km2), 3), "flow_km2": round(float(wet.sum() * a_km2), 3),
               "both_km2": round(inter * a_km2, 3), "csi": round(inter / union, 2) if union else None,
               "share_of_hand_also_wet": round(inter / max(int(hand.sum()), 1), 2)}
    except Exception as e:  # noqa: BLE001
        log.warning("flow %s: HAND comparison failed: %s", run_id, e)
    from app.pipeline.emulator import TRIGGER_DEPTH_M, _people_grid
    ppl = _people_grid(area)  # residents per cell (buildings + unattributed), inside the drawn area
    people = {"in_water": int(round(float(ppl[wet].sum()))),
              "knee_deep": int(round(float(ppl[(res.hmax >= TRIGGER_DEPTH_M) & aoi & ~perm].sum())))}
    first = res.t_arrival_s[wet]
    meta = {
        "state": "ready", "progress": 1.0, "model": MODEL, "frame_s": frame_s, "frames": int(frames.shape[0]), "tail_h": TAIL_H,
        "width": grid.width, "height": grid.height, "cell": grid.cell, "model_cell_m": grid.cell * m["k"], "ground": m["ground"],
        "h_code_m": swe.H_CODE, "u_code_ms": swe.U_CODE,
        "h_show_m": swe.H_SHOW, "arf": round(m["arf"], 3), "drain_mm_h": m["drain_mm_h"], "drain_where": "built-up cells (Dynamic World)",
        "sources": [{k: s[k] for k in ("reach_id", "q", "outside_km2")} for s in m["sources"]],
        "max_depth_m": round(float(res.hmax[aoi & ~perm].max()), 2) if (aoi & ~perm).any() else 0.0,
        "max_speed_ms": round(float(res.vmax[wet].max()), 1) if wet.any() else 0.0,
        "flooded_km2": round(float(wet.sum() * a_km2), 3), "hazard_km2": hazard_km2,
        "first_flooding_min": round(float(first.min()) / 60) if first.size else None,
        "compare_hand": cmp, "people": people, "stats": res.stats, "total_s": round(time.time() - t0, 1),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    _status(run_id, **meta)
    log.info("flow %s: %s", run_id, json.dumps(res.stats))
    return meta


def store_later(run_id: str, area, sim: dict, static_depth: np.ndarray | None = None) -> None:
    """`store` on the flow pool; until it finishes the run's flow status reads "running" (start() will not re-run it)."""
    _status(run_id, state="running", progress=0.99, started_at=datetime.now(timezone.utc).isoformat())
    # a newer run of the same area replaces an upload still waiting: its frames (tens of MB on a large area) are not
    # held in memory behind a busy worker; that older run's 3D simulates again if it is ever opened
    old = _pending_store.get(area.aoi_id)
    if old and old[1].cancel():
        _jobs.pop(old[0], None)
        _status(old[0], state="none", progress=0.0)

    def job() -> None:
        if _pending_store.get(area.aoi_id, ("",))[0] == run_id:  # started: no longer replaceable
            _pending_store.pop(area.aoi_id, None)
        try:
            store(run_id, area, sim, static_depth)
        except Exception as e:  # noqa: BLE001
            log.exception("flow %s: store failed", run_id)
            _status(run_id, state="failed", error=f"{e.__class__.__name__}: {e}"[:300])
        finally:
            _jobs.pop(run_id, None)
    fut = _pool.submit(job)
    _jobs[run_id] = fut
    _pending_store[area.aoi_id] = (run_id, fut)


def simulate_run(run_id: str) -> dict:
    """Run the flow model for a stored run and store frames (flow/frames.bin) and maxima (flow/summary.npz); runs made
    since 17 Oct already did this inside the run."""
    from app.pipeline.run_pipeline import load_area
    run = fs.get_doc("runs", run_id)
    if not run:
        raise KeyError(run_id)
    area = load_area(run["aoi_id"])
    rain = [float(x) for x in run["rain_series_mm_h"]]
    last = [0.0]

    def progress(f: float) -> None:
        _progress[run_id] = f
        if f - last[0] >= 0.1:
            last[0] = f
            _status(run_id, progress=round(f, 2))

    return store(run_id, area, simulate(area, rain, run.get("params") or {}, progress))


def _job(run_id: str) -> None:
    try:
        simulate_run(run_id)
    except Exception as e:  # noqa: BLE001
        log.exception("flow %s failed", run_id)
        _status(run_id, state="failed", error=f"{e.__class__.__name__}: {e}"[:300])
    finally:
        _jobs.pop(run_id, None)
        _progress.pop(run_id, None)


def start(run_id: str, force: bool = False) -> dict:
    """Queue the flow model for a run unless it is running or done."""
    if run_id in _jobs:
        return status(run_id)
    doc = fs.get_doc(COLL, run_id) or {}
    if doc.get("state") == "ready" and not force:
        return doc
    _status(run_id, state="queued", progress=0.0, started_at=datetime.now(timezone.utc).isoformat())
    _jobs[run_id] = _pool.submit(_job, run_id)
    return {"state": "queued", "progress": 0.0}


def status(run_id: str) -> dict:
    doc = fs.get_doc(COLL, run_id) or {"state": "none"}
    if run_id in _progress:
        doc = {**doc, "state": "running", "progress": round(_progress[run_id], 3)}
    elif doc.get("state") in ("queued", "running") and run_id not in _jobs:
        # running on another instance, or that instance is gone: stale only after 5 min without progress
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(doc.get("updated_at", ""))).total_seconds()
        except ValueError:
            age = 1e9
        if age > 300:
            doc = {**doc, "state": "stale"}
    return doc


def _static_depth(run_id: str) -> np.ndarray:
    """River + hollow depth [H, rows, cols] without the flow model: static_depth.npz for runs since 17 Oct (their
    depth.npz includes the flow model), else depth.npz."""
    name = "static_depth.npz" if storage.run_exists(run_id, "static_depth.npz") else "depth.npz"
    return np.load(io.BytesIO(storage.get_run(run_id, name)))["depth"].astype(np.float32)


def hand_frames(run_id: str) -> bytes:
    """The HAND map's hourly depth in the same frame format (no velocity), for comparison in 3D."""
    d = _static_depth(run_id)
    d = np.nan_to_num(d, nan=0.0)
    z = np.zeros(d.shape[1:], np.float32)
    frames = [swe.encode_frame(z, z, z)] + [swe.encode_frame(d[t], z, z) for t in range(d.shape[0])]
    return np.stack(frames).tobytes()
