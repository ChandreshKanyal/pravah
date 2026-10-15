"""Proxy structure classes from footprint, height and density (S6.1-S6.3). Labels are "likely ...", never fact.

Classifies structures only, never people.
"""
import numpy as np
from scipy.spatial import cKDTree

# class -> (fragility F, base confidence)
CLASSES = {
    "makeshift_or_hut": 1.0,
    "informal_cluster": 0.75,
    "likely_kaccha_or_low_rise": 0.80,
    "new_unplanned_low_rise": 0.80,
    "likely_pukka_multi_storey": 0.20,
    "likely_pukka_low_rise": 0.45,
}


def cluster_flags(x: np.ndarray, y: np.ndarray, area_m2: np.ndarray, radius_m: float = 30.0,
                  min_count: int = 8, max_mean_area: float = 60.0) -> np.ndarray:
    """True where >= min_count buildings (incl. itself) lie within radius and their mean area < max_mean_area."""
    if len(x) == 0:
        return np.zeros(0, bool)
    tree = cKDTree(np.column_stack([x, y]))
    nbrs = tree.query_ball_point(np.column_stack([x, y]), r=radius_m)
    a = np.asarray(area_m2, dtype=float)
    count = np.array([len(n) for n in nbrs])
    mean_area = np.array([a[n].mean() for n in nbrs])
    return (count >= min_count) & (mean_area < max_mean_area)


def classify(area_m2, height_m, presence_2016, presence_2023, cluster) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(class, F, confidence, floors) per building; rules applied in order, first match wins."""
    a = np.asarray(area_m2, dtype=float)
    h = np.asarray(height_m, dtype=float)
    p16 = np.asarray(presence_2016, dtype=float)
    p23 = np.asarray(presence_2023, dtype=float)
    cl = np.asarray(cluster, dtype=bool)
    no_h = ~np.isfinite(h)
    with np.errstate(invalid="ignore"):
        rules = [
            (no_h & (a < 25), "makeshift_or_hut", 0.35),
            ((h < 3.5) & (a < 40), "makeshift_or_hut", 0.50),
            (cl, "informal_cluster", 0.45),
            ((h < 4.5) & (a < 120), "likely_kaccha_or_low_rise", 0.40),
            ((p16 < 0.3) & (p23 >= 0.5) & (h < 4.5), "new_unplanned_low_rise", 0.35),
            (h >= 6.5, "likely_pukka_multi_storey", 0.55),
        ]
    n = len(a)
    cls = np.full(n, "likely_pukka_low_rise", dtype=object)
    conf = np.full(n, 0.40)
    done = np.zeros(n, bool)
    for mask, name, c in rules:
        m = mask & ~done
        cls[m], conf[m], done = name, c, done | m
    F = np.array([CLASSES[c] for c in cls], dtype=float)
    floors = np.where(no_h, 1, np.maximum(1, np.round(np.nan_to_num(h) / 3.2))).astype(int)
    return cls, F, conf, floors


def apply_field_overrides(bids, cls, F, conf, overrides: dict[str, dict]) -> np.ndarray:
    """S6.3: photo classification with confidence >= 0.6 replaces class and F. Returns the `source` array."""
    source = np.full(len(bids), "proxy", dtype=object)
    for i, b in enumerate(bids):
        o = overrides.get(b)
        if o and o.get("confidence", 0) >= 0.6 and o.get("class") in CLASSES:
            cls[i], F[i], conf[i], source[i] = o["class"], CLASSES[o["class"]], o["confidence"], "field_photo"
    return source
