"""Flood susceptibility index, static, AHP-weighted (S4). Pure NumPy."""
import numpy as np

from app.engines.ahp import ahp_weights

FSI_FACTORS = ["hand", "hist", "dist_stream", "upa", "rain", "slope", "C"]
FSI_MATRIX = [
    [1, 1, 2, 2, 2, 2, 3],
    [1, 1, 1, 1, 1, 2, 2],
    [1 / 2, 1, 1, 1, 1, 2, 2],
    [1 / 2, 1, 1, 1, 1, 2, 2],
    [1 / 2, 1, 1, 1, 1, 1, 2],
    [1 / 2, 1 / 2, 1 / 2, 1 / 2, 1, 1, 1],
    [1 / 3, 1 / 2, 1 / 2, 1 / 2, 1 / 2, 1, 1],
]
GFD_MAX_HAND_M = 20.0
GFD_MAX_SLOPE_DEG = 10.0
CLASS_EDGES = [0.2, 0.4, 0.6, 0.8]  # very low / low / moderate / high / very high
CLASS_NAMES = ["very low", "low", "moderate", "high", "very high"]


def factor_scores(hand, gfd_count, gsw_occ, dist_stream_m, upa, rain_clim, slope_deg, C,
                  hand_max=30.0, dist_max=1000.0, rain_lo=50.0, rain_hi=300.0, slope_max=30.0) -> dict[str, np.ndarray]:
    """Each factor mapped to 0..1 (1 = more susceptible). Missing values score 0 (C: grid mean)."""
    z = np.nan_to_num
    # satellite flood counts (MODIS 250 m) also mark cloud shadow and snow on ridges; a flood pixel high above the
    # drainage or on a steep slope is physically implausible and is not counted (checked 16 Oct: Rudraprayag ridge
    # pixels 460-600 m above the river)
    plausible = (z(hand, nan=hand_max) <= GFD_MAX_HAND_M) & (z(slope_deg, nan=slope_max) <= GFD_MAX_SLOPE_DEG)
    gfd = np.where(plausible, z(gfd_count), 0).astype(float)
    p99 = max(1.0, float(np.percentile(gfd, 99)))
    upa = z(upa)
    C = np.asarray(C, dtype=float)
    return {
        "hand": 1 - np.minimum(z(hand, nan=hand_max) / hand_max, 1),
        "hist": np.maximum(np.minimum(gfd / p99, 1), z(gsw_occ) / 100),
        "dist_stream": 1 - np.minimum(z(dist_stream_m, nan=dist_max) / dist_max, 1),
        "upa": np.log10(1 + upa) / np.log10(1 + max(float(upa.max()), 1e-9)),
        "rain": np.clip((z(rain_clim) - rain_lo) / (rain_hi - rain_lo), 0, 1),
        "slope": 1 - np.minimum(z(slope_deg, nan=slope_max) / slope_max, 1),
        "C": np.where(np.isfinite(C), C, np.nanmean(C) if np.isfinite(C).any() else 0.5),
    }


def fsi(scores: dict[str, np.ndarray], matrix=FSI_MATRIX) -> tuple[np.ndarray, np.ndarray, dict]:
    """(fsi 0..1, class 1..5, {weights, cr})."""
    w, _, _, cr = ahp_weights(matrix)
    val = sum(wk * scores[f] for wk, f in zip(w, FSI_FACTORS)).astype(np.float32)
    cls = (np.digitize(val, CLASS_EDGES) + 1).astype(np.uint8)
    return val, cls, {"factors": FSI_FACTORS, "weights": [round(float(x), 4) for x in w], "cr": round(float(cr), 4)}
