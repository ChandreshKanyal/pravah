"""Landslide susceptibility: static (AHP weights x FR or expert ratings) and rainfall-modulated (S5). Pure NumPy.

Output is susceptibility, never a timed prediction.
"""
import numpy as np

from app.engines.ahp import ahp_weights
from app.engines.fr import fr_ratings, frequency_ratio
from app.engines.rainfall import caine_threshold

LSI_FACTORS = ["slope", "rain", "ndvi", "drain", "road", "soil", "curv", "aspect"]
LSI_MATRIX = [
    [1, 1, 2, 2, 2, 2, 2, 3],
    [1, 1, 1, 2, 2, 2, 2, 3],
    [1 / 2, 1, 1, 1, 1, 1, 2, 2],
    [1 / 2, 1 / 2, 1, 1, 1, 1, 1, 2],
    [1 / 2, 1 / 2, 1, 1, 1, 1, 1, 2],
    [1 / 2, 1 / 2, 1, 1, 1, 1, 1, 2],
    [1 / 2, 1 / 2, 1 / 2, 1, 1, 1, 1, 1],
    [1 / 3, 1 / 3, 1 / 2, 1 / 2, 1 / 2, 1 / 2, 1, 1],
]
# class bin edges (inner edges; classes are 0..len(edges)); rain uses training-region quintiles
BINS = {
    "slope": [15, 25, 35, 45],
    "ndvi": [0.2, 0.4, 0.6],
    "drain": [100, 300, 600],
    "road": [50, 150, 300],
    "soil": [15, 30, 45],
    "curv": [-0.5, 0.5],  # concave, flat, convex
}
N_CLASSES = {"slope": 5, "rain": 5, "ndvi": 4, "drain": 4, "road": 4, "soil": 4, "curv": 3, "aspect": 9}
EXPERT = {
    "slope": [0.1, 0.4, 0.7, 1.0, 0.8],
    "rain": [0.2, 0.4, 0.6, 0.8, 1.0],
    "ndvi": [1.0, 0.7, 0.4, 0.2],
    "drain": [1.0, 0.7, 0.4, 0.2],
    "road": [1.0, 0.7, 0.4, 0.2],
    "soil": [0.3, 0.6, 0.9, 0.7],
    "curv": [0.8, 0.4, 0.5],
    "aspect": [0.4, 0.4, 0.5, 0.6, 0.6, 0.6, 0.5, 0.4, 0.1],  # N NE E SE S SW W NW flat
}
MIN_SLIDES = 15
FLAT_SLOPE_DEG = 5.0


def aspect_class(aspect_deg: np.ndarray) -> np.ndarray:
    """0..7 = N, NE, ..., NW; 8 = flat (aspect -1)."""
    a = np.asarray(aspect_deg, dtype=float)
    cls = (((a + 22.5) // 45) % 8).astype(np.int16)
    return np.where(a < 0, 8, cls).astype(np.int16)


def classify(layers: dict[str, np.ndarray], rain_edges: list[float]) -> dict[str, np.ndarray]:
    """Class index per factor (int16), -1 where the input is missing."""
    out = {}
    for f, key in (("slope", "slope_deg"), ("ndvi", "ndvi"), ("drain", "dist_stream_m"), ("road", "dist_road_m"),
                   ("soil", "soil_clay"), ("curv", "curv")):
        v = np.asarray(layers[key], dtype=float)
        out[f] = np.where(np.isfinite(v), np.digitize(np.nan_to_num(v), BINS[f]), -1).astype(np.int16)
    r = np.asarray(layers["rain_clim"], dtype=float)
    out["rain"] = np.where(np.isfinite(r), np.digitize(np.nan_to_num(r), rain_edges), -1).astype(np.int16)
    out["aspect"] = aspect_class(layers["aspect_deg"])
    return out


def rain_quintile_edges(rain_clim_training: np.ndarray) -> list[float]:
    v = np.asarray(rain_clim_training, dtype=float)
    v = v[np.isfinite(v)]
    return np.percentile(v, [20, 40, 60, 80]).tolist() if v.size else [0, 0, 0, 0]


def learn_ratings(classes: dict[str, np.ndarray], slides: np.ndarray, factors: list[str],
                  n_points: int | None = None) -> tuple[dict[str, list[float]], int]:
    """FR ratings for `factors` when at least 15 landslide records exist, else expert ratings. Returns (ratings, n)."""
    n = int(np.count_nonzero(slides)) if n_points is None else int(n_points)
    ratings = {f: list(EXPERT[f]) for f in LSI_FACTORS}
    if n >= MIN_SLIDES:
        for f in factors:
            ratings[f] = fr_ratings(frequency_ratio(classes[f], slides, N_CLASSES[f])).round(4).tolist()
    return ratings, n


def lsi_raw(classes: dict[str, np.ndarray], ratings: dict[str, list[float]], matrix=LSI_MATRIX) -> tuple[np.ndarray, dict]:
    w, _, _, cr = ahp_weights(matrix)
    total = None
    for wk, f in zip(w, LSI_FACTORS):
        lut = np.asarray(ratings[f], dtype=float)
        c = classes[f]
        mean_r = float(lut.mean())
        r = np.where(c >= 0, lut[np.clip(c, 0, len(lut) - 1)], mean_r)  # missing input -> mean rating
        total = wk * r if total is None else total + wk * r
    return total.astype(np.float32), {"factors": LSI_FACTORS, "weights": [round(float(x), 4) for x in w], "cr": round(float(cr), 4)}


def normalise_and_classify(raw: np.ndarray, train_raw: np.ndarray, slope_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[float]]:
    """Min-max by the training region; classes 1..5 at training quantiles 20/40/60/80; slope < 5 deg -> class 1."""
    lo, hi = float(np.nanmin(train_raw)), float(np.nanmax(train_raw))
    norm = lambda x: np.clip((x - lo) / ((hi - lo) or 1.0), 0, 1)  # noqa: E731
    val = norm(raw).astype(np.float32)
    edges = np.percentile(norm(train_raw[np.isfinite(train_raw)]), [20, 40, 60, 80]).tolist()
    cls = (np.digitize(val, edges) + 1).astype(np.uint8)
    cls[np.nan_to_num(slope_deg) < FLAT_SLOPE_DEG] = 1
    return val, cls, edges


def rain_modulation(rain_mm_h) -> np.ndarray:
    """g[t] = clip(I_mean(1..t) / I_thr(t), 0.5, 1.5) with Caine's threshold, D = t hours."""
    i = np.asarray(rain_mm_h, dtype=float)
    t = np.arange(1, len(i) + 1)
    return np.clip((np.cumsum(i) / t) / caine_threshold(t), 0.5, 1.5)


def lsi_dynamic_classes(lsi_static: np.ndarray, edges: list[float], rain_mm_h, slope_deg: np.ndarray) -> np.ndarray:
    """uint8 [H, rows, cols] classes of clip(lsi_static * g[t], 0, 1), same thresholds and flat mask."""
    g = rain_modulation(rain_mm_h)
    flat = np.nan_to_num(slope_deg) < FLAT_SLOPE_DEG
    out = np.empty((len(g),) + lsi_static.shape, np.uint8)
    for t, gt in enumerate(g):
        c = (np.digitize(np.clip(lsi_static * gt, 0, 1), edges) + 1).astype(np.uint8)
        c[flat] = 1
        out[t] = c
    return out
