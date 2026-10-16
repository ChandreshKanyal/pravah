"""Raster to RGBA PNG for map overlays (S1.14). Pure, no I/O."""
import io

import numpy as np
from PIL import Image
from scipy import ndimage

from app.engines.grid import corner_lonlats
from app.models.grid import GridSpec

# colour stops, low to high (RGB)
COLORMAPS: dict[str, list[tuple[int, int, int]]] = {
    "blues": [(239, 243, 255), (107, 174, 214), (8, 48, 107)],
    "hand": [(8, 48, 107), (66, 146, 198), (198, 219, 239), (255, 255, 255)],  # low HAND = dark blue
    "terrain": [(26, 152, 80), (217, 239, 139), (254, 224, 139), (215, 48, 39), (255, 255, 255)],
    "risk": [(255, 255, 178), (254, 178, 76), (240, 59, 32), (128, 0, 38)],
}


def to_png(array: np.ndarray, colormap: str = "blues", vmin: float | None = None, vmax: float | None = None,
           nodata_transparent: bool = True, alpha: int = 200) -> bytes:
    a = np.asarray(array, dtype=np.float64)
    valid = np.isfinite(a)
    if vmin is None:
        vmin = float(np.nanmin(a)) if valid.any() else 0.0
    if vmax is None:
        vmax = float(np.nanmax(a)) if valid.any() else 1.0
    t = np.clip((np.where(valid, a, vmin) - vmin) / ((vmax - vmin) or 1.0), 0, 1)
    stops = np.array(COLORMAPS[colormap], dtype=np.float64)
    pos = t * (len(stops) - 1)
    i = np.minimum(pos.astype(int), len(stops) - 2)
    f = (pos - i)[..., None]
    rgb = stops[i] * (1 - f) + stops[i + 1] * f
    a_ch = np.where(valid | (not nodata_transparent), alpha, 0)
    rgba = np.dstack([rgb, a_ch]).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def overlay_payload(grid: GridSpec) -> dict:
    return {"corners": corner_lonlats(grid)}


DEPTH_EDGES = [0.05, 0.5, 1.0, 1.5, 3.0]  # S16.8
DEPTH_COLORS = ["#c6dbef", "#9ecae1", "#6baed6", "#3182bd", "#08519c"]
SUSCEPT_COLORS = ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"]
WATER_COLOR = "#2f6db5"
UPSAMPLE = 3  # display PNGs at cell/3 (10 m for 30 m grids) so class edges read as smooth contours, not blurred squares


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _smooth_mask(mask: np.ndarray, k: int, sigma_cells: float = 0.35, level: float = 0.42) -> np.ndarray:
    """Upsample a boolean cell mask by k with rounded edges: bilinear, a light Gaussian, then an iso-line. sigma 0.35 cell
    and level 0.42 keep the coloured area within a few % of the cell mask (tuned on the Rudraprayag run: 0.98-1.03) and
    keep single-cell channels, so the picture stays faithful to the model."""
    z = ndimage.zoom(mask.astype(np.float32), k, order=1, grid_mode=True, mode="grid-constant", cval=0.0)
    return ndimage.gaussian_filter(z, sigma_cells * k, mode="constant") >= level


def to_png_binned(array: np.ndarray, edges: list[float], colors: list[str], nan_color: str | None = None,
                  alpha: int = 210, upsample: int = UPSAMPLE) -> bytes:
    """Bin k covers [edges[k], edges[k+1]); the last bin is open-ended. Below edges[0] is transparent.
    NaN is transparent unless `nan_color` is given (e.g. permanent water). Display only: rendered at `upsample` x the
    grid with each threshold's outline smoothed (bins are nested, so bin = number of thresholds passed - 1); the image
    footprint equals the cell grid, so the overlay corners are unchanged."""
    a = np.asarray(array, dtype=np.float64)
    if upsample > 1 and a.ndim == 2 and min(a.shape) >= 2:
        filled = np.nan_to_num(a, nan=-np.inf)
        k = sum(_smooth_mask(filled >= e, upsample).astype(np.int8) for e in edges) - 1
        nan = _smooth_mask(np.isnan(a), upsample)
        a = np.where(nan, np.nan, 0.0)  # only the NaN layout is used below
    else:
        k = np.digitize(np.nan_to_num(a, nan=-np.inf), edges) - 1  # -1 below first edge
    rgba = np.zeros(a.shape + (4,), np.uint8)
    for i, c in enumerate(colors):
        m = k == i
        rgba[m, :3] = _rgb(c)
        rgba[m, 3] = alpha
    if nan_color:
        m = np.isnan(a)
        rgba[m, :3] = _rgb(nan_color)
        rgba[m, 3] = alpha
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", compress_level=6)
    return buf.getvalue()


def to_png_classes(classes: np.ndarray, colors: list[str] = SUSCEPT_COLORS, alpha: int = 170) -> bytes:
    """Integer classes 1..len(colors); 0 or less is transparent."""
    edges = [k - 0.5 for k in range(1, len(colors) + 1)]  # class k falls in [k-0.5, k+0.5)
    return to_png_binned(np.asarray(classes, dtype=float), edges, colors, alpha=alpha)
