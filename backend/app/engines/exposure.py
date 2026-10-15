"""Exposure per hour, building risk, triage, clusters and the field verification queue (S6.5-S6.9). Pure NumPy."""
from collections import Counter, defaultdict

import numpy as np

WET_M = 0.05
RISK_ORDER = ["critical", "high", "moderate", "low"]


def risk_class(R: np.ndarray) -> np.ndarray:
    return np.select([R >= 0.7, R >= 0.5, R >= 0.3], ["critical", "high", "moderate"], "low").astype(object)


def building_risk(d_b, F, dist_stream_m, ls_b) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(R_b, risk class, reason) at the evaluation hour (S6.6)."""
    d = np.nan_to_num(np.asarray(d_b, dtype=float))
    ls = np.asarray(ls_b)
    D = np.minimum(d / 3.0, 1)
    P = 1 - np.minimum(np.nan_to_num(np.asarray(dist_stream_m, dtype=float), nan=300.0) / 300.0, 1)
    R = 0.5 * D + 0.3 * np.asarray(F, dtype=float) + 0.2 * P
    R = np.where((d < WET_M) & (ls <= 3), 0.0, R)
    cls = risk_class(R)
    reason = np.where(d >= WET_M, "flood", "").astype(object)
    slide = ls >= 4
    raise_ = slide & np.isin(cls, ["moderate", "low"])
    cls[raise_] = "high"
    reason[slide] = np.where(reason[slide] == "flood", "flood+landslide", "landslide")
    return R, cls, reason


def per_hour(depth: np.ndarray, lsi_dyn: np.ndarray | None, rows, cols, pop_b, pop_unattr) -> dict:
    """Exposed people per hour by flood depth >= 0.05 m and by landslide class >= 4."""
    H = depth.shape[0]
    d_b = np.nan_to_num(depth[:, rows, cols])  # [H, n]
    flood = [int(round(pop_b[d_b[t] >= WET_M].sum() + pop_unattr[np.nan_to_num(depth[t]) >= WET_M].sum()))
             for t in range(H)]
    slide = [0] * H
    ls_b = np.zeros_like(d_b, dtype=np.uint8)
    if lsi_dyn is not None:
        ls_b = lsi_dyn[:, rows, cols]
        slide = [int(round(pop_b[ls_b[t] >= 4].sum() + pop_unattr[lsi_dyn[t] >= 4].sum())) for t in range(H)]
    worst = d_b[-1]
    wu = np.nan_to_num(depth[-1])
    bands = {}
    for name, lo, hi in (("0.05-0.5", 0.05, 0.5), ("0.5-1.5", 0.5, 1.5), (">1.5", 1.5, np.inf)):
        bands[name] = int(round(pop_b[(worst >= lo) & (worst < hi)].sum() + pop_unattr[(wu >= lo) & (wu < hi)].sum()))
    return {"d_b": d_b, "ls_b": ls_b, "exposed_pop_by_hour": flood, "landslide_exposed_pop_by_hour": slide,
            "exposed_by_depth_band": bands}


def triage(struct_cls, risk_cls, pop_b) -> list[dict]:
    """Rows {structure_class, risk_class, buildings, people}, sorted by risk then people."""
    agg: dict[tuple, list] = defaultdict(lambda: [0, 0.0])
    for s, r, p in zip(struct_cls, risk_cls, pop_b):
        agg[(s, r)][0] += 1
        agg[(s, r)][1] += p
    rows = [{"structure_class": s, "risk_class": r, "buildings": n, "people": int(round(p))} for (s, r), (n, p) in agg.items()]
    return sorted(rows, key=lambda x: (RISK_ORDER.index(x["risk_class"]), -x["people"]))


def clusters(rows, cols, pop_b, R, risk_cls, struct_cls, d_b_worst, exposed, depth_worst, pop_unattr,
             block: int, to_lonlat, top: int = 20) -> list[dict]:
    """Aggregate exposed buildings + exposed grid population into block x block cells (300 m); top by people x risk."""
    groups: dict[tuple, dict] = defaultdict(lambda: {"people": 0.0, "rp": 0.0, "max_depth": 0.0, "classes": Counter()})
    for i in np.flatnonzero(exposed):
        g = groups[(rows[i] // block, cols[i] // block)]
        g["people"] += pop_b[i]
        g["rp"] += pop_b[i] * R[i]
        g["max_depth"] = max(g["max_depth"], float(d_b_worst[i]))
        g["classes"][struct_cls[i]] += 1
    wet = np.nan_to_num(depth_worst) >= WET_M
    for r, c in zip(*np.nonzero(wet & (pop_unattr > 0))):
        g = groups[(r // block, c // block)]
        p = float(pop_unattr[r, c])
        Rg = 0.5 * min(float(depth_worst[r, c]) / 3.0, 1) + 0.3 * 0.8  # unknown structure: assume F = 0.8
        g["people"] += p
        g["rp"] += p * Rg
        g["max_depth"] = max(g["max_depth"], float(depth_worst[r, c]))
    out = []
    for (br, bc), g in groups.items():
        if g["people"] <= 0:
            continue
        risk = g["rp"] / g["people"]
        lon, lat = to_lonlat((br + 0.5) * block - 0.5, (bc + 0.5) * block - 0.5)
        out.append({"centroid": [round(float(lon), 6), round(float(lat), 6)], "people": int(round(g["people"])),
                    "max_depth": round(g["max_depth"], 2), "risk": round(float(risk), 3),
                    "risk_class": str(risk_class(np.array([risk]))[0]),
                    "dominant_class": g["classes"].most_common(1)[0][0] if g["classes"] else "unattributed"})
    out.sort(key=lambda x: -x["people"] * x["risk"])
    for k, c in enumerate(out[:top], start=1):
        c["id"] = f"C{k}"
    return out[:top]


def verification_queue(bids, R, confidence, pop_b, lon, lat, struct_cls, top: int = 50) -> list[dict]:
    """score = R_b x (1 - confidence) x pop_b: buildings to check in the field first."""
    score = np.asarray(R) * (1 - np.asarray(confidence)) * np.asarray(pop_b)
    idx = [i for i in np.argsort(-score)[:top] if score[i] > 0]
    return [{"bid": bids[i], "lon": round(float(lon[i]), 6), "lat": round(float(lat[i]), 6),
             "current_class": struct_cls[i], "score": round(float(score[i]), 3), "people": round(float(pop_b[i]), 1)}
            for i in idx]
