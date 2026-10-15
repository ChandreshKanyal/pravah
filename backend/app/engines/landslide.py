"""Landslide susceptibility: static (AHP weights x FR or expert ratings) and rainfall-modulated (S5). Pure NumPy.

Output is susceptibility, never a timed prediction.
"""
import numpy as np

from app.engines.ahp import ahp_weights
from app.engines.fr import fr_ratings, frequency_ratio
from app.engines.rainfall import LANDSLIDE_THRESHOLDS, landslide_threshold

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


def exceedance(rain_mm_h, threshold: str = "caine") -> np.ndarray:
    """R[t] = I_mean(1..t) / I_thr(D = t hours) for an intensity-duration threshold (see rainfall.LANDSLIDE_THRESHOLDS)."""
    i = np.asarray(rain_mm_h, dtype=float)
    t = np.arange(1, len(i) + 1)
    return (np.cumsum(i) / t) / landslide_threshold(t, threshold)


def rain_modulation(rain_mm_h, g_slope: float = 0.25, g_min: float = 0.75, g_max: float = 1.25,
                    threshold: str = "caine") -> np.ndarray:
    """g[t] from R = I_mean(1..t) / I_thr(t), D = t hours.

    NOTE(spec-drift): the spec's g = clip(R, 0.5, 1.5) saturates for any rain above ~13 mm/h over 4 h, so we use a
    graded g = clip(1 + g_slope * log2(R), g_min, g_max): each doubling of R adds g_slope (human decision, 16 Oct).
    `threshold` picks the I-D curve; Himalayan AOIs default to Dahal & Hasegawa (2008) instead of Caine's global one.
    """
    assert threshold in LANDSLIDE_THRESHOLDS
    R = exceedance(rain_mm_h, threshold)
    with np.errstate(divide="ignore"):
        return np.clip(1 + g_slope * np.log2(np.maximum(R, 1e-9)), g_min, g_max)


def auc(score: np.ndarray, positive: np.ndarray) -> float | None:
    """Area under the ROC curve of `score` for `positive` cells (Mann-Whitney U, ties averaged). None if undefined."""
    from scipy.stats import rankdata
    s = np.asarray(score, dtype=float).ravel()
    y = np.asarray(positive, dtype=bool).ravel()
    ok = np.isfinite(s)
    s, y = s[ok], y[ok]
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return None
    r = rankdata(s)
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def class_shift(R) -> np.ndarray:
    """Per-hour class shift from threshold exceedance R: -1 below the threshold, 0 up to twice it, +1 beyond."""
    R = np.asarray(R, dtype=float)
    return np.where(R < 1.0, -1, np.where(R >= 2.0, 1, 0)).astype(np.int16)


def lsi_dynamic_classes(lsi_static: np.ndarray, edges: list[float], rain_mm_h, slope_deg: np.ndarray,
                        mode: str = "class_shift", threshold: str = "caine", **g_kwargs) -> np.ndarray:
    """uint8 [H, rows, cols] rainfall-modulated classes, same thresholds and flat mask.

    mode "class_shift" (default): static class + class_shift(R[t]), clipped to 1..5. A decision-matrix modulation in
    the spirit of LHASA: rain moves a slope by at most one class, so the narrow LSI class bands cannot be jumped.
    mode "graded_g": classes of clip(lsi_static * g[t], 0, 1) (16 Oct; a x1.25 boost jumped ~2 classes here).
    """
    flat = np.nan_to_num(slope_deg) < FLAT_SLOPE_DEG
    if mode == "class_shift":
        base = (np.digitize(lsi_static, edges) + 1).astype(np.int16)
        shifts = class_shift(exceedance(rain_mm_h, threshold))
        out = np.empty((len(shifts),) + lsi_static.shape, np.uint8)
        for t, d in enumerate(shifts):
            c = np.clip(base + d, 1, 5).astype(np.uint8)
            c[flat] = 1
            out[t] = c
        return out
    g = rain_modulation(rain_mm_h, threshold=threshold, **g_kwargs)
    out = np.empty((len(g),) + lsi_static.shape, np.uint8)
    for t, gt in enumerate(g):
        c = (np.digitize(np.clip(lsi_static * gt, 0, 1), edges) + 1).astype(np.uint8)
        c[flat] = 1
        out[t] = c
    return out


def actionable(lsi_dyn: np.ndarray, triggered: np.ndarray, cap: int = 3) -> np.ndarray:
    """Classes used for decisions (closures, evacuation, shelter exclusion, risk raise): hours where rainfall does not
    exceed the I-D threshold are capped at `cap`, as LHASA (Kirschbaum & Stanley 2018) issues no landslide hazard
    without the rainfall trigger. The uncapped classes stay on the map as susceptibility."""
    trig = np.asarray(triggered, bool).reshape(-1, *([1] * (lsi_dyn.ndim - 1)))
    return np.where(trig, lsi_dyn, np.minimum(lsi_dyn, cap)).astype(lsi_dyn.dtype)
