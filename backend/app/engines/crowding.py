"""Crowding and evacuation-difficulty index from open data only (S9). Pure NumPy; never uses Maps traffic data."""
import numpy as np
from scipy.ndimage import gaussian_filter

ATTRACTORS = [  # (tag, values or None for any, weight, label)
    ("amenity", {"marketplace"}, 1.0, "market"),
    ("amenity", {"bus_station"}, 1.0, "bus station"),
    ("public_transport", {"station"}, 1.0, "station"),
    ("railway", {"station"}, 1.0, "railway station"),
    ("amenity", {"place_of_worship"}, 0.8, "place of worship"),
    ("tourism", {"hotel", "guest_house", "hostel"}, 0.6, "lodging"),
    ("amenity", {"school", "college", "hospital"}, 0.6, "school/college/hospital"),
    ("shop", None, 0.2, "shop"),
]


def poi_weight(row: dict) -> tuple[float, str]:
    best, label = 0.0, ""
    for tag, vals, w, lab in ATTRACTORS:
        v = row.get(tag)
        if v is None or str(v) in ("", "nan", "<NA>", "None"):
            continue
        if (vals is None or str(v) in vals) and w > best:
            best, label = w, lab
    return best, label


def crowd_grid(shape: tuple[int, int], poi_rc: list[tuple[int, int, float]], bld_rows, bld_cols,
               cell: float = 30.0, sigma_m: float = 100.0, return_raw: bool = False):
    """POI weights + 0.5 x building count per cell, Gaussian-smoothed, normalised to 0..1 (clip at p99).
    With return_raw, also returns the unclipped smoothed grid (for ranking hotspots without ties)."""
    g = np.zeros(shape, np.float64)
    for r, c, w in poi_rc:
        if 0 <= r < shape[0] and 0 <= c < shape[1]:
            g[r, c] += w
    br, bc = np.asarray(bld_rows, int), np.asarray(bld_cols, int)
    ok = (br >= 0) & (br < shape[0]) & (bc >= 0) & (bc < shape[1])
    np.add.at(g, (br[ok], bc[ok]), 0.5)
    g = gaussian_filter(g, sigma=sigma_m / cell)
    p99 = float(np.percentile(g, 99))
    out = np.clip(g / p99, 0, 1).astype(np.float32) if p99 > 0 else g.astype(np.float32)
    return (out, g) if return_raw else out


def edge_crowd(crowd: np.ndarray, cells: list[int], narrowness: float) -> float:
    """crowd_e = 0.6 x max(crowd along edge) + 0.4 x narrowness."""
    m = float(crowd.ravel()[cells].max()) if len(cells) else 0.0
    return 0.6 * m + 0.4 * narrowness
