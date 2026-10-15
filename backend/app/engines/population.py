"""Population to buildings (S6.4). Pure NumPy."""
import numpy as np


def distribute(pop30: np.ndarray, rows: np.ndarray, cols: np.ndarray, area_m2: np.ndarray,
               height_m: np.ndarray, block: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """pop_b = pop[block] * vol / sum(vol in block); blocks without buildings keep their people unattributed
    (per 30 m cell). `block` = 3 shares people over 90 m blocks, matching WorldPop's ~100 m resolution.
    Buildings outside the grid get 0. Returns (pop_b, pop_unattributed grid)."""
    pop = np.nan_to_num(np.asarray(pop30, dtype=np.float64))
    h, w = pop.shape
    bh, bw = -(-h // block), -(-w // block)
    r, c = np.asarray(rows), np.asarray(cols)
    inside = (r >= 0) & (r < h) & (c >= 0) & (c < w)
    vol = np.asarray(area_m2, dtype=float) * np.maximum(np.nan_to_num(np.asarray(height_m, dtype=float), nan=3.0), 3.0)
    bidx = np.where(inside, (r // block) * bw + (c // block), -1)
    rr, cc = np.indices((h, w))
    cell_block = ((rr // block) * bw + (cc // block)).ravel()
    pop_block = np.bincount(cell_block, weights=pop.ravel(), minlength=bh * bw)
    vol_block = np.bincount(bidx[inside], weights=vol[inside], minlength=bh * bw)
    pop_b = np.zeros(len(vol))
    pop_b[inside] = pop_block[bidx[inside]] * vol[inside] / vol_block[bidx[inside]]
    unattributed = np.where(vol_block[cell_block].reshape(h, w) > 0, 0.0, pop)
    return pop_b, unattributed


def scale_factor(current_total: float, pop_multiplier: float = 1.0, pop_total_override: int | None = None) -> float:
    """Multiplier, then optional rescale to an override total."""
    k = pop_multiplier
    if pop_total_override is not None and current_total * k > 0:
        k = pop_total_override / current_total
    return k
