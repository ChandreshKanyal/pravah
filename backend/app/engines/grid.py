"""Analysis grid (SPEC §4.2) and terrain derivatives (S1.7). Pure NumPy/pyproj, no I/O."""
import math

import numpy as np
from pyproj import Transformer

from app.models.grid import GridSpec


def utm_epsg(lon: float, lat: float) -> int:
    zone = int((lon + 180) / 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def _to_utm(crs: str) -> Transformer:
    return Transformer.from_crs("EPSG:4326", crs, always_xy=True)


def _to_lonlat(crs: str) -> Transformer:
    return Transformer.from_crs(crs, "EPSG:4326", always_xy=True)


def make_grid(bbox: tuple[float, float, float, float], buffer_m: float = 3000, cell: float = 30, snap: float = 90) -> GridSpec:
    """Buffered bbox in the UTM zone of its centroid, snapped outward to multiples of `snap` m."""
    w, s, e, n = bbox
    crs = f"EPSG:{utm_epsg((w + e) / 2, (s + n) / 2)}"
    xs, ys = _to_utm(crs).transform([w, e, e, w], [s, s, n, n])
    minx = math.floor((min(xs) - buffer_m) / snap) * snap
    maxx = math.ceil((max(xs) + buffer_m) / snap) * snap
    miny = math.floor((min(ys) - buffer_m) / snap) * snap
    maxy = math.ceil((max(ys) + buffer_m) / snap) * snap
    return GridSpec(crs=crs, x0=minx, y0=maxy, cell=cell,
                    width=int(round((maxx - minx) / cell)), height=int(round((maxy - miny) / cell)))


def cell_centers_xy(grid: GridSpec) -> tuple[np.ndarray, np.ndarray]:
    """1-D arrays of column-centre x and row-centre y (m)."""
    xs = grid.x0 + (np.arange(grid.width) + 0.5) * grid.cell
    ys = grid.y0 - (np.arange(grid.height) + 0.5) * grid.cell
    return xs, ys


def xy_to_rowcol(grid: GridSpec, x, y):
    col = np.floor((np.asarray(x) - grid.x0) / grid.cell).astype(int)
    row = np.floor((grid.y0 - np.asarray(y)) / grid.cell).astype(int)
    return row, col


def lonlat_to_rowcol(grid: GridSpec, lon, lat):
    x, y = _to_utm(grid.crs).transform(lon, lat)
    return xy_to_rowcol(grid, x, y)


def rowcol_to_lonlat(grid: GridSpec, r, c):
    x = grid.x0 + (np.asarray(c) + 0.5) * grid.cell
    y = grid.y0 - (np.asarray(r) + 0.5) * grid.cell
    return _to_lonlat(grid.crs).transform(x, y)


def corner_lonlats(grid: GridSpec) -> list[list[float]]:
    """Grid corners as [lon, lat] in deck.gl BitmapLayer order: bottom-left, top-left, top-right, bottom-right."""
    x1 = grid.x0 + grid.width * grid.cell
    y1 = grid.y0 - grid.height * grid.cell
    lons, lats = _to_lonlat(grid.crs).transform([grid.x0, grid.x0, x1, x1], [y1, grid.y0, grid.y0, y1])
    return [[float(lo), float(la)] for lo, la in zip(lons, lats)]


def lonlat_bounds(grid: GridSpec) -> tuple[float, float, float, float]:
    """WGS84 (west, south, east, north) enclosing the grid."""
    c = np.array(corner_lonlats(grid))
    return float(c[:, 0].min()), float(c[:, 1].min()), float(c[:, 0].max()), float(c[:, 1].max())


def terrain(dem: np.ndarray, cell: float) -> dict[str, np.ndarray]:
    """slope_deg, aspect_deg (0 = N, -1 where flat), curv (1/100 m, negative = concave). Rows increase southward."""
    gx = np.gradient(dem, axis=1) / cell  # east
    gy = -np.gradient(dem, axis=0) / cell  # north
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    aspect = (np.degrees(np.arctan2(-gx, -gy)) + 360) % 360
    aspect = np.where(slope < 1, -1.0, aspect)
    d2x = np.gradient(np.gradient(dem, axis=1), axis=1) / cell**2
    d2y = np.gradient(np.gradient(dem, axis=0), axis=0) / cell**2
    curv = -100 * (d2x + d2y)
    return {"slope_deg": slope.astype(np.float32), "aspect_deg": aspect.astype(np.float32), "curv": curv.astype(np.float32)}
