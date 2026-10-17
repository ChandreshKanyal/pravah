"""Train, validate and serve the per-area AI emulator of the 2D flow model (engines/emulator.py), and derive
anticipatory-action rain triggers from it.

Training set: a scrambled Sobol design over storm duration (1-6 h), storm size (the wettest hours of a 40-450 mm day
by the IMD reduction rule), timing (steady or early-peaked IMD design storm) and, in river mode, river level above
normal (0-3 m). Each design point is one full shallow-water run (the same inputs as the 3D view). Runs go through the
flow model's single worker one at a time, so 3D jobs queued meanwhile still get their turn.

Triggers: for each OSM settlement, the smallest early-peaked storm (mm in 1, 3 and 6 h) at which at least
max(25 people, 5 % of its residents) are in water at least 30 cm deep at home. They come from the physics model itself,
not the emulator: a sweep of 12 storm sizes per duration is run through the shallow-water model and each place's
threshold is interpolated between the two sizes that bracket it (these runs also join the emulator's training set).
A storm total is also expressed as the equivalent IMD 24-hour category, so a district can tie each place to the IMD
warning colour that should trigger action there.
"""
import io
import logging
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np
from scipy.spatial import cKDTree
from scipy.stats import qmc

from app.engines import emulator as em
from app.engines import rainfall
from app.engines.grid import lonlat_to_rowcol
from app.services import firestore as fs, storage

log = logging.getLogger(__name__)
COLL = "emulators"
N_TRAIN = 64  # a power of two keeps the Sobol design balanced
DURATIONS = [1, 2, 3, 4, 6]
P24_RANGE = (40.0, 450.0)
OFFSET_MAX = 3.0
TRIGGER_DURATIONS = [1, 3, 6]
TRIGGER_DEPTH_M = 0.3  # knee-deep: walking becomes unsafe for children and the elderly; ground floors take water
TRIGGER_MIN_PEOPLE = 25
TRIGGER_SHARE = 0.05
SWEEP_LEVELS = 12
BIG_GRID_CELLS = 200_000  # above this, a lighter design (32 storms, 10 sweep sizes) keeps training under an hour
METHOD = ("Reduced-order emulator: SVD (proper orthogonal decomposition) of peak depth over {n} shallow-water runs from "
          "a Sobol design, pattern weights regressed on storm features by thin-plate-spline RBF; leave-one-out validated")
_lock = threading.Lock()
_running: set[str] = set()


def _status(aoi_id: str, final: bool = False, **fields) -> None:
    """Progress is best effort (a slow Firestore write must not kill a 30-minute training); the final state retries."""
    for attempt in range(3 if final else 1):
        try:
            fs.merge_doc(COLL, aoi_id, {**fields, "updated_at": datetime.now(timezone.utc).isoformat()})
            return
        except Exception as e:  # noqa: BLE001
            log.warning("emulator %s: status write failed (%s)", aoi_id, e)
            time.sleep(2 * (attempt + 1))


def design(urban: bool, n: int = N_TRAIN, seed: int = 7) -> list[dict]:
    """Space-filling training storms: [{duration_h, p24_mm, shape, river_offset_m, rain}]."""
    d = 3 if urban else 4
    u = qmc.Sobol(d, scramble=True, seed=seed).random_base2(int(np.log2(n)))
    out = []
    for i in range(n):
        H = DURATIONS[min(int(u[i, 0] * len(DURATIONS)), len(DURATIONS) - 1)]
        p24 = P24_RANGE[0] + u[i, 1] * (P24_RANGE[1] - P24_RANGE[0])
        shape = "triangular_front" if u[i, 2] >= 0.5 else "constant"
        off = 0.0 if urban else round(float(u[i, 3]) * OFFSET_MAX, 2)
        total = rainfall.daily_to_duration_mm(p24, H)
        out.append({"duration_h": H, "p24_mm": round(float(p24), 1), "shape": shape, "river_offset_m": off,
                    "rain": rainfall.distribute_total(total, H, shape)})
    # the two corners a district asks about most: a short cloudburst and a long extreme storm
    out.append({"duration_h": 1, "p24_mm": 288.4, "shape": "constant", "river_offset_m": 0.0, "rain": [100.0]})
    out.append({"duration_h": 6, "p24_mm": P24_RANGE[1], "shape": "triangular_front", "river_offset_m": 0.0 if urban else OFFSET_MAX,
                "rain": rainfall.distribute_total(rainfall.daily_to_duration_mm(P24_RANGE[1], 6), 6, "triangular_front")})
    return out


def sweep_design(levels: int = SWEEP_LEVELS) -> list[dict]:
    """Physics sweep for the triggers: SWEEP_LEVELS early-peaked storms per trigger duration, river at normal level."""
    out = []
    for H in TRIGGER_DURATIONS:
        hi = rainfall.daily_to_duration_mm(P24_RANGE[1], H)
        for P in np.linspace(10.0, hi, levels):
            out.append({"duration_h": H, "p24_mm": round(float(P / (H / 24) ** (1 / 3)), 1), "shape": "triangular_front",
                        "river_offset_m": 0.0, "rain": rainfall.distribute_total(float(P), H, "triangular_front"), "sweep": True})
    return out


def start(aoi_id: str, force: bool = False) -> dict:
    st = fs.get_doc(COLL, aoi_id) or {}
    with _lock:
        if aoi_id in _running:
            return {"state": "running"}
        if st.get("state") == "ready" and not force:
            return {"state": "ready"}
        _running.add(aoi_id)
    threading.Thread(target=_train_job, args=(aoi_id,), daemon=True).start()
    return {"state": "queued"}


def _train_job(aoi_id: str) -> None:
    try:
        train(aoi_id)
    except Exception as e:  # noqa: BLE001
        log.exception("emulator %s failed", aoi_id)
        _status(aoi_id, final=True, state="failed", error=f"{e.__class__.__name__}: {e}")
    finally:
        with _lock:
            _running.discard(aoi_id)


def train(aoi_id: str, sweep_only: bool = False) -> dict:
    """Full training, or `sweep_only`: keep the stored emulator and rerun only the trigger sweep."""
    from app.pipeline import flow
    from app.pipeline.run_pipeline import load_area
    t0 = time.time()
    area = load_area(aoi_id)
    urban = area.pluvial is not None
    big = area.grid.width * area.grid.height > BIG_GRID_CELLS
    model_k = 2 if big else None  # big grids train on the 60 m version of the model (4x cheaper)
    old = meta_json(aoi_id) if sweep_only else None
    sweep_only = sweep_only and old is not None and _load(aoi_id) is not None
    runs = (sweep_design(10 if big else SWEEP_LEVELS) if sweep_only
            else design(urban, 32 if big else N_TRAIN) + sweep_design(10 if big else SWEEP_LEVELS))
    _status(aoi_id, state="running", progress=0.0, n_train=len(runs), started_at=datetime.now(timezone.utc).isoformat(), error=None)
    drain = _drain(area)
    X, Y = [], []
    for i, r in enumerate(runs):
        params = {"river_offset_m": r["river_offset_m"]}
        h = flow._pool.submit(flow.run_maxima, area, r["rain"], params, model_k).result()  # shares the flow model's worker
        X.append(em.features(r["rain"], r["river_offset_m"], drain))
        Y.append(h.ravel())
        _status(aoi_id, progress=round((i + 1) / (len(runs) + 1), 3))
    X, Y = np.array(X), np.array(Y, np.float32)
    sweep = {}
    for r, y in zip(runs, Y):
        if r.get("sweep"):
            sweep.setdefault(r["duration_h"], []).append((float(sum(r["rain"])), y.reshape(area.grid.height, area.grid.width)))
    shape = area.grid.height, area.grid.width
    if sweep_only:  # triggers only: the stored emulator and its validation stay
        trig = triggers(aoi_id, sweep, area)
        storage.put_json(aoi_id, "emulator/triggers.json", trig)
        meta = {**old, "triggers": len(trig["places"]), "triggers_at": datetime.now(timezone.utc).isoformat(),
                "trigger_runs": len(runs), "state": "ready", "progress": 1.0}
        storage.put_json(aoi_id, "emulator/meta.json", meta)
        _status(aoi_id, final=True, state="ready", progress=1.0, triggers=meta["triggers"], triggers_at=meta["triggers_at"])
        return meta
    mask = (area.aoi_mask if area.aoi_mask is not None else np.ones(shape, bool)) & ~np.asarray(area.perm, bool)
    loo = em.leave_one_out(X, Y, shape, mask)
    model = em.Emulator(X, Y, shape)
    buf = io.BytesIO()
    np.savez_compressed(buf, **model.state())
    storage.put_bytes(aoi_id, "emulator/model.npz", buf.getvalue())
    _load.cache_clear()
    csi = np.array([s["csi"] for s in loo])
    mae = np.array([s["mae_m"] for s in loo])
    inside = np.array([not s["outside_range"] for s in loo])
    trig = triggers(aoi_id, sweep, area)
    storage.put_json(aoi_id, "emulator/triggers.json", trig)
    meta = {
        "state": "ready", "progress": 1.0, "method": METHOD.format(n=len(runs)) + ("; runs on 60 m cells" if model_k else ""),
        "model_cell_m": area.grid.cell * (model_k or 1), "n_train": len(runs), "modes": model.k,
        "energy": round(model.energy, 4), "features": em.FEATURES,
        "range": {f: [round(float(a), 1), round(float(b), 1)] for f, a, b in zip(em.FEATURES, model.lo, model.hi)},
        "validation": {"csi_median": round(float(np.median(csi[inside])), 3) if inside.any() else None,
                       "csi_p10": round(float(np.percentile(csi[inside], 10)), 3) if inside.any() else None,
                       "mae_m_median": round(float(np.median(mae[inside])), 3) if inside.any() else None,
                       "runs_inside_range": int(inside.sum()), "per_run": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()} for s in loo]},
        "design": [{k: v for k, v in r.items() if k != "rain"} | {"total_mm": round(sum(r["rain"]), 1)} for r in runs],
        "triggers": len(trig["places"]), "train_s": round(time.time() - t0, 1), "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    storage.put_json(aoi_id, "emulator/meta.json", meta)
    _status(aoi_id, final=True, **{k: v for k, v in meta.items() if k not in ("design",)} | {"validation": {k: v for k, v in meta["validation"].items() if k != "per_run"}})
    log.info("emulator %s: %d runs, CSI median %s, %.0f s", aoi_id, len(runs), meta["validation"]["csi_median"], meta["train_s"])
    return meta


@lru_cache(maxsize=4)
def _load(aoi_id: str) -> em.Emulator | None:
    if not storage.exists(aoi_id, "emulator/model.npz"):
        return None
    with np.load(io.BytesIO(storage.get_bytes(aoi_id, "emulator/model.npz"))) as z:
        return em.Emulator.from_state({k: z[k] for k in z.files})


def _drain(area) -> float:
    from app.config import get_settings
    return get_settings().urban_drain_capacity_mm_h if area.pluvial is not None else 0.0


def storm(total_mm: float, hours: int, shape: str) -> list[float]:
    return rainfall.distribute_total(float(total_mm), int(hours), shape)


def _people_grid(area) -> np.ndarray:
    """Residents per cell: mapped buildings' people plus people not attributed to a building."""
    g = np.zeros((area.grid.height, area.grid.width), np.float64)
    if area.bld is not None and len(area.bld.get("row", [])):
        np.add.at(g, (area.bld["row"].astype(int), area.bld["col"].astype(int)), area.bld["pop_base"].astype(float))
    if area.pop_unattr is not None:
        g += np.nan_to_num(np.asarray(area.pop_unattr, np.float64))
    if area.aoi_mask is not None:
        g[~area.aoi_mask] = 0
    return g


def predict(aoi_id: str, total_mm: float, hours: int, shape: str = "triangular_front", river_offset_m: float = 0.0):
    """(peak depth grid, stats) or (None, None) if the area has no emulator yet."""
    from app.pipeline.run_pipeline import load_area
    model = _load(aoi_id)
    if model is None:
        return None, None
    area = load_area(aoi_id)
    x = em.features(storm(total_mm, hours, shape), river_offset_m, _drain(area))
    _, outside = model.clamp(x)
    t = time.perf_counter()
    h = _despeckle(model.predict(x))
    ms = (time.perf_counter() - t) * 1000
    mask = (area.aoi_mask if area.aoi_mask is not None else np.ones(h.shape, bool)) & ~np.asarray(area.perm, bool)
    a_km2 = area.grid.cell**2 / 1e6
    ppl = _people_grid(area)
    stats = {"flooded_km2": round(float(((h >= em.WET_M) & mask).sum() * a_km2), 3),
             "max_depth_m": round(float(h[mask].max()), 2) if mask.any() else 0.0,
             "people_in_water": int(round(float(ppl[(h >= TRIGGER_DEPTH_M) & mask].sum()))),
             "outside_trained_range": outside, "ms": round(ms, 1),
             "imd_category": imd_category(total_mm, hours)}
    return h, stats


def _despeckle(h: np.ndarray, min_cells: int = 3) -> np.ndarray:
    """Drop wet patches smaller than `min_cells` cells: reconstruction noise, not floods."""
    from scipy.ndimage import label
    lab, n = label(h >= em.WET_M)
    if n == 0:
        return h
    size = np.bincount(lab.ravel())
    small = size < min_cells
    small[0] = False
    out = h.copy()
    out[small[lab]] = 0.0
    return out


def imd_category(total_mm: float, hours: int) -> str:
    """The IMD 24-hour category whose wettest `hours` hours (reduction rule) hold this much rain."""
    p24 = float(total_mm) / (min(max(int(hours), 1), 24) / 24) ** (1 / 3)
    return ("below heavy" if p24 < 64.5 else "heavy" if p24 <= 115.5 else "very heavy" if p24 <= 204.4 else "extremely heavy")


def triggers(aoi_id: str, sweep: dict[int, list[tuple[float, np.ndarray]]], area) -> dict:
    """Per-settlement rain thresholds from the physics sweep {duration: [(storm total mm, peak depth grid), ...]}."""
    from app.services.places import area_places
    places = [p for p in area_places(aoi_id, area.grid, wait=True) if p.get("name")]
    ppl = _people_grid(area)
    rr, cc = np.nonzero(ppl > 0)
    if not places or not len(rr):
        return {"depth_m": TRIGGER_DEPTH_M, "places": [], "durations": TRIGGER_DURATIONS}
    pr, pc = zip(*(lonlat_to_rowcol(area.grid, p["lon"], p["lat"]) for p in places))
    _, owner = cKDTree(np.c_[pr, pc]).query(np.c_[rr, cc])  # each populated cell belongs to its nearest settlement
    pop = np.bincount(owner, weights=ppl[rr, cc], minlength=len(places))
    need = np.maximum(TRIGGER_MIN_PEOPLE, TRIGGER_SHARE * pop)
    out = {i: {} for i in range(len(places))}
    hi_by_h = {}
    for H in TRIGGER_DURATIONS:
        runs = sorted(sweep.get(H, []), key=lambda t: t[0])
        if not runs:
            continue
        hi_by_h[H] = round(runs[-1][0])
        P = np.array([t[0] for t in runs])
        W = np.array([np.bincount(owner, weights=ppl[rr, cc] * (h[rr, cc] >= TRIGGER_DEPTH_M), minlength=len(places)) for _, h in runs])
        W = np.maximum.accumulate(W, axis=0)  # more rain never dries a place: remove solver noise between sizes
        for i in range(len(places)):
            k = np.flatnonzero(W[:, i] >= need[i])
            if not len(k) or pop[i] < TRIGGER_MIN_PEOPLE:
                out[i][H] = None
                continue
            k = int(k[0])
            if k == 0:
                out[i][H] = int(round(P[0]))
                continue
            w0, w1 = W[k - 1, i], W[k, i]  # linear between the bracketing storm sizes
            f = (need[i] - w0) / (w1 - w0) if w1 > w0 else 1.0
            out[i][H] = int(round(P[k - 1] + f * (P[k] - P[k - 1])))
    rows = []
    for i, p in enumerate(places):
        if pop[i] < TRIGGER_MIN_PEOPLE or all(v is None for v in out[i].values()):
            continue
        th = {str(H): out[i].get(H) for H in TRIGGER_DURATIONS}
        rows.append({"name": p["name"], "name_hi": p.get("name_hi", ""), "kind": p.get("kind", ""), "lon": p["lon"], "lat": p["lat"],
                     "residents": int(round(pop[i])), "thresholds_mm": th,
                     "imd": {str(H): imd_category(v, H) if v is not None else None for H, v in out[i].items()}})
    rows.sort(key=lambda r: (r["thresholds_mm"]["3"] if r["thresholds_mm"]["3"] is not None else 1e9, -r["residents"]))
    return {"depth_m": TRIGGER_DEPTH_M, "min_people": TRIGGER_MIN_PEOPLE, "share": TRIGGER_SHARE, "durations": TRIGGER_DURATIONS,
            "storm": "early-peaked IMD design storm", "method": f"2D shallow-water model, {len(sweep.get(TRIGGER_DURATIONS[0], []))} storm sizes per duration, interpolated",
            "max_trained_mm": {str(k): v for k, v in hi_by_h.items()}, "places": rows,
            "note": "River at its normal level; a river already running high lowers every threshold."}


def status(aoi_id: str) -> dict:
    st = fs.get_doc(COLL, aoi_id) or {"state": "none"}
    if aoi_id in _running and st.get("state") not in ("running",):
        st["state"] = "queued"
    return st


def meta_json(aoi_id: str) -> dict | None:
    return storage.get_json(aoi_id, "emulator/meta.json") if storage.exists(aoi_id, "emulator/meta.json") else None


def triggers_json(aoi_id: str) -> dict | None:
    return storage.get_json(aoi_id, "emulator/triggers.json") if storage.exists(aoi_id, "emulator/triggers.json") else None

