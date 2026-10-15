"""Raster to RGBA PNG for map overlays (S1.14). Pure, no I/O."""
import io

import numpy as np
from PIL import Image

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
