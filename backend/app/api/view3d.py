"""S19 3D view (option B, our own data only): Terrain-RGB from the Copernicus DEM grid, an hourly texture
(hillshade + flood depth) on the same UTM grid, and Open Buildings footprints with ground height and run risk.
Coordinates are metre offsets from the grid centre so terrain, texture and buildings align exactly.
Never uses the Maps Elevation API (Maps terms 3.2.3(c)(iii))."""
import io
import json

import numpy as np
from fastapi import APIRouter, HTTPException, Response
from google.api_core.exceptions import NotFound
from PIL import Image

from app.engines.render import DEPTH_COLORS, DEPTH_EDGES, _rgb
from app.services import storage

router = APIRouter()


def _png(rgb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, "PNG", optimize=True)
    return buf.getvalue()


@router.get("/api/aoi/{aoi_id}/3d/meta")
def meta(aoi_id: str):
    try:
        grid = storage.load_grid(aoi_id)
        dem = storage.load_layers(aoi_id, "terrain")["dem"]
    except NotFound:
        raise HTTPException(404, "Area not prepared")
    from app.engines.grid import rowcol_to_lonlat
    lon, lat = rowcol_to_lonlat(grid, (grid.height - 1) / 2, (grid.width - 1) / 2)
    W, H = grid.width * grid.cell, grid.height * grid.cell
    from app.engines.grid import lonlat_bounds
    return {"origin": [float(lon), float(lat)], "bounds_m": [-W / 2, -H / 2, W / 2, H / 2],
            "bounds_ll": [float(x) for x in lonlat_bounds(grid)],
            "z_min": float(np.nanmin(dem)), "z_max": float(np.nanmax(dem)), "cell": grid.cell}


@router.get("/api/aoi/{aoi_id}/3d/dem.bin")
def dem_bin(aoi_id: str, step: int = 2):
    """DEM block-averaged by `step` as little-endian float32, row-major from the north-west corner; header in
    X-Grid: "width,height,cell"."""
    dem = storage.load_layers(aoi_id, "terrain")["dem"].astype(np.float64)
    grid = storage.load_grid(aoi_id)
    step = int(min(max(step, 1), 4))
    h, w = (dem.shape[0] // step) * step, (dem.shape[1] // step) * step
    d = np.nan_to_num(dem[:h, :w], nan=float(np.nanmin(dem))).reshape(h // step, step, w // step, step).mean(axis=(1, 3))
    return Response(d.astype("<f4").tobytes(), media_type="application/octet-stream",
                    headers={"X-Grid": f"{d.shape[1]},{d.shape[0]},{grid.cell * step}", "Access-Control-Expose-Headers": "X-Grid",
                             "Cache-Control": "public, max-age=86400"})


@router.get("/api/aoi/{aoi_id}/3d/terrain.png")
def terrain(aoi_id: str):
    """Mapbox Terrain-RGB encoding: height = -10000 + (R*65536 + G*256 + B) * 0.1."""
    dem = np.nan_to_num(storage.load_layers(aoi_id, "terrain")["dem"].astype(np.float64), nan=0.0)
    v = np.clip(np.round((dem + 10000) * 10), 0, 2**24 - 1).astype(np.uint32)
    rgb = np.stack([(v >> 16) & 255, (v >> 8) & 255, v & 255], axis=-1).astype(np.uint8)
    return Response(_png(rgb), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


def _hillshade(dem: np.ndarray, cell: float) -> np.ndarray:
    gy, gx = np.gradient(np.nan_to_num(dem), cell)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.radians(315), np.radians(45)
    hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    return np.clip(hs, 0, 1)


@router.get("/api/runs/{run_id}/3d/texture_h{hour}.png")
def texture(run_id: str, hour: int, aoi_id: str):
    """Hillshaded terrain tinted green-brown by elevation, with the run's flood depth at `hour` on top."""
    key = f"png/tex3d_h{hour}.png"
    try:
        return Response(storage.get_run(run_id, key), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
    except NotFound:
        pass
    grid = storage.load_grid(aoi_id)
    dem = storage.load_layers(aoi_id, "terrain")["dem"].astype(np.float64)
    hs = _hillshade(dem, grid.cell)
    z = (np.nan_to_num(dem) - np.nanpercentile(dem, 2)) / max(1.0, np.nanpercentile(dem, 98) - np.nanpercentile(dem, 2))
    low, high = np.array([110, 140, 90]), np.array([190, 175, 150])
    base = (low + np.clip(z, 0, 1)[..., None] * (high - low)) * (0.45 + 0.75 * hs[..., None])
    try:
        depth = np.load(io.BytesIO(storage.get_run(run_id, "depth.npz")))["depth"].astype(np.float32)
    except NotFound:
        raise HTTPException(404, "Run not found")
    d = depth[min(max(hour, 1), depth.shape[0]) - 1]
    rgb = base.copy()
    k = np.digitize(np.nan_to_num(d, nan=-1), DEPTH_EDGES) - 1
    for i, c in enumerate(DEPTH_COLORS):
        m = k == i
        rgb[m] = 0.25 * rgb[m] + 0.75 * np.array(_rgb(c))
    rgb[np.isnan(d)] = np.array([70, 110, 160]) * (0.6 + 0.4 * hs[np.isnan(d)][..., None])  # permanent river
    out = _png(np.clip(rgb, 0, 255).astype(np.uint8))
    storage.put_run(run_id, key, out, "image/png")
    return Response(out, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/api/runs/{run_id}/3d/buildings.json")
def buildings(run_id: str, aoi_id: str):
    """[{p: [[x, y], ...] metre offsets, z: ground m, h: height m, r: risk 0 critical..3 low}] (cached per run)."""
    try:
        return Response(storage.get_run(run_id, "buildings3d.json"), media_type="application/json")
    except NotFound:
        pass
    grid = storage.load_grid(aoi_id)
    b = storage.load_gdf(aoi_id, "buildings_proxy.parquet")
    b = b.to_crs(grid.crs) if str(b.crs) != str(grid.crs) else b
    dem = storage.load_layers(aoi_id, "terrain")["dem"]
    try:
        risk = np.load(io.BytesIO(storage.get_run(run_id, "bld_risk.npy")))
    except NotFound:
        risk = np.full(len(b), 3, np.uint8)
    cx, cy = grid.x0 + grid.width * grid.cell / 2, grid.y0 - grid.height * grid.cell / 2
    rows = np.clip(b["row"].to_numpy(int), 0, grid.height - 1)
    cols = np.clip(b["col"].to_numpy(int), 0, grid.width - 1)
    z = np.nan_to_num(dem[rows, cols])
    hgt = np.nan_to_num(b["height_m"].to_numpy(float), nan=3.0)
    out = []
    for i, g in enumerate(b.geometry):
        poly = max(g.geoms, key=lambda q: q.area) if g.geom_type == "MultiPolygon" else g
        if poly.is_empty:
            continue
        pts = [[round(x - cx, 1), round(y - cy, 1)] for x, y in poly.simplify(0.5).exterior.coords]
        out.append({"p": pts, "z": round(float(z[i]), 1), "h": round(float(max(hgt[i], 2.5)), 1),
                    "r": int(risk[i]) if i < len(risk) else 3})
    data = json.dumps(out, separators=(",", ":")).encode()
    storage.put_run(run_id, "buildings3d.json", data, "application/json")
    return Response(data, media_type="application/json")
