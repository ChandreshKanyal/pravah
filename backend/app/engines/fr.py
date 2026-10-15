"""Frequency Ratio (Lee & Pradhan 2007). Pure NumPy."""
import numpy as np


def frequency_ratio(classes: np.ndarray, slides: np.ndarray, n_classes: int) -> np.ndarray:
    """FR_k = (slides in k / total slides) / (cells in k / total cells). Cells with class -1 are ignored."""
    c = np.asarray(classes).ravel()
    s = np.asarray(slides, dtype=bool).ravel()
    valid = c >= 0
    c, s = c[valid], s[valid]
    cells = np.bincount(c, minlength=n_classes).astype(float)
    hits = np.bincount(c[s], minlength=n_classes).astype(float)
    total_cells, total_hits = cells.sum(), hits.sum()
    if total_hits == 0 or total_cells == 0:
        return np.zeros(n_classes)
    return np.divide(hits / total_hits, cells / total_cells, out=np.zeros(n_classes), where=cells > 0)


def fr_ratings(fr: np.ndarray) -> np.ndarray:
    """r_k = FR_k / max_k FR_k."""
    m = float(np.max(fr)) if len(fr) else 0.0
    return fr / m if m > 0 else np.zeros_like(fr)
