"""S19 3D view (our own data only): the ground the 2D flow model runs on (FABDEM bare earth, hydrologically conditioned
in hilly areas) as a height grid, a terrain picture (Sentinel-2 true colour, or a hillshade with rivers), Open Buildings
footprints with ground height, and per-run building risk. Water comes from /api/runs/{id}/flow (api/flow.py).
Coordinates are metre offsets from the grid centre, so terrain, water and buildings align exactly.
Never uses the Maps Elevation API (Maps terms 3.2.3(c)(iii))."""
import gzip
import io
import json
import threading
from functools import lru_cache

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Response
from google.api_core.exceptions import NotFound
from PIL import Image
from scipy import ndimage

from app.auth import require
from app.engines.render import DEPTH_COLORS, DEPTH_EDGES, _rgb, _smooth_mask
from app.services import firestore as fs, storage
from app.services.terrain import flow_ground

TEX_K = 3  # texture at cell/3 (10 m) so rivers, streams and flood edges are crisp on the mesh
RIVER = np.array([66, 133, 214.0])
S2_KEY = "png/s2_rgb_v1.jpg"
_s2_busy: set[str] = set()

router = APIRouter()


def _jpeg(rgb: np.ndarray, q: int = 85) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).save(buf, "JPEG", quality=q)
    return buf.getvalue()


@router.get("/api/aoi/{aoi_id}/3d/meta")
def meta(aoi_id: str):
    try:
        grid = storage.load_grid(aoi_id)
        dem, ground = flow_ground(aoi_id)
    except NotFound:
        raise HTTPException(404, "Area not prepared")
    from app.engines.grid import _to_utm, lonlat_bounds, rowcol_to_lonlat
    lon, lat = rowcol_to_lonlat(grid, (grid.height - 1) / 2, (grid.width - 1) / 2)
    W, H = grid.width * grid.cell, grid.height * grid.cell
    threading.Thread(target=_tex_base, args=(aoi_id,), daemon=True).start()  # warm the terrain picture
    aoi_m = None
    doc = fs.get_aoi(aoi_id) or {}
    bbox = doc.get("bbox")
    if bbox:
        w, s_, e, n = bbox
        t = _to_utm(grid.crs)
        cx, cy = grid.x0 + W / 2, grid.y0 - H / 2
        aoi_m = [[round(x - cx, 1), round(y - cy, 1)] for x, y in (t.transform(lo, la) for lo, la in [(w, s_), (e, s_), (e, n), (w, n), (w, s_)])]
    return {"origin": [float(lon), float(lat)], "bounds_m": [-W / 2, -H / 2, W / 2, H / 2], "aoi_m": aoi_m,
            "bounds_ll": [float(x) for x in lonlat_bounds(grid)], "mode": doc.get("mode", "auto"), "profile": (doc.get("meta") or {}).get("profile"),
            "z_min": float(np.nanmin(dem)), "z_max": float(np.nanmax(dem)), "cell": grid.cell,
            "width": grid.width, "height": grid.height, "ground": ground,
            "imagery": storage.exists(aoi_id, S2_KEY)}


@router.get("/api/aoi/{aoi_id}/3d/dem.bin")
def dem_bin(aoi_id: str, step: int = 1):
    """Ground heights (the flow model's ground) block-averaged by `step`, little-endian float32, row-major from the
    north-west corner, gzip-encoded; header X-Grid: "width,height,cell"."""
    dem = np.asarray(flow_ground(aoi_id)[0], np.float64)
    grid = storage.load_grid(aoi_id)
    step = int(min(max(step, 1), 4))
    h, w = (dem.shape[0] // step) * step, (dem.shape[1] // step) * step
    d = np.nan_to_num(dem[:h, :w], nan=float(np.nanmin(dem))).reshape(h // step, step, w // step, step).mean(axis=(1, 3))
    return Response(gzip.compress(d.astype("<f4").tobytes(), 5), media_type="application/octet-stream",
                    headers={"X-Grid": f"{d.shape[1]},{d.shape[0]},{grid.cell * step}", "Access-Control-Expose-Headers": "X-Grid",
                             "Content-Encoding": "gzip", "Cache-Control": "public, max-age=3600"})


def _hillshade(dem: np.ndarray, cell: float) -> np.ndarray:
    gy, gx = np.gradient(np.nan_to_num(dem), cell)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.radians(315), np.radians(45)
    hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    return np.clip(hs, 0, 1)


@lru_cache(maxsize=4)
def _tex_base(aoi_id: str) -> np.ndarray:
    """Per-area picture at 3x the grid: terrain tinted by elevation with a soft hillshade (the 3D view lights the relief
    itself), rivers (JRC surface water present >= 50 % of the time) and main streams (>= 10 km2 upstream) in blue.
    Context only, not model output."""
    grid = storage.load_grid(aoi_id)
    dem = np.asarray(flow_ground(aoi_id)[0], np.float64)
    k = TEX_K
    demf = ndimage.zoom(np.nan_to_num(dem, nan=float(np.nanmin(dem))).astype(np.float32), k, order=1, grid_mode=True, mode="nearest")
    hs = _hillshade(demf, grid.cell / k)
    p2, p98 = np.nanpercentile(dem, 2), np.nanpercentile(dem, 98)
    z = np.clip((demf - p2) / max(1.0, p98 - p2), 0, 1)
    low, high = np.array([96, 128, 78.0]), np.array([196, 182, 156.0])
    rgb = (low + z[..., None] * (high - low)) * (0.7 + 0.4 * hs[..., None])
    river = np.zeros(demf.shape, bool)
    try:
        river |= _smooth_mask(np.nan_to_num(storage.load_layers(aoi_id, "hazard_hist")["gsw_occ"]) >= 50, k)
    except (NotFound, KeyError):
        pass
    try:
        h30 = storage.load_layers(aoi_id, "hydro30")
        river |= _smooth_mask(h30["stream"] & (np.nan_to_num(h30["upa"]) >= 10.0), k, sigma_cells=0.3, level=0.35)
    except (NotFound, KeyError):
        pass
    rgb[river] = RIVER * (0.85 + 0.15 * hs[river][..., None])
    return rgb.astype(np.float32)


@router.get("/api/aoi/{aoi_id}/3d/base.jpg")
def base_texture(aoi_id: str):
    """Hillshaded terrain with rivers and main streams (shown while the satellite picture loads, or without it)."""
    try:
        rgb = _tex_base(aoi_id)
    except NotFound:
        raise HTTPException(404, "Area not prepared")
    return Response(_jpeg(rgb), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})


def _make_s2(aoi_id: str) -> None:
    try:
        from app.services import earth_engine as ees
        rgb = ees.s2_rgb(storage.load_grid(aoi_id), TEX_K)
        storage.put_bytes(aoi_id, S2_KEY, _jpeg(rgb, 88), "image/jpeg")
    finally:
        _s2_busy.discard(aoi_id)


@router.get("/api/aoi/{aoi_id}/3d/imagery.jpg")
def imagery(aoi_id: str):
    """Sentinel-2 true colour (cloud-masked dry-season median, 10 m) on the grid. 202 while it is being made (first
    request per area, about 10-30 s); the page keeps the hillshade until it is ready."""
    try:
        return Response(storage.get_bytes(aoi_id, S2_KEY), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
    except NotFound:
        pass
    if aoi_id not in _s2_busy:
        _s2_busy.add(aoi_id)
        threading.Thread(target=_make_s2, args=(aoi_id,), daemon=True).start()
    return Response(status_code=202, headers={"Retry-After": "5"})


@router.get("/api/runs/{run_id}/3d/texture_h{hour}.jpg")
def texture(run_id: str, hour: int, aoi_id: str):
    """Hillshade picture with the run's HAND flood depth at `hour` (nested smoothed bands, as on the 2D map)."""
    key = f"png/tex3d_v3_h{hour}.jpg"
    hdr = {"Cache-Control": "public, max-age=86400"}
    try:
        return Response(storage.get_run(run_id, key), media_type="image/jpeg", headers=hdr)
    except NotFound:
        pass
    try:
        depth = np.load(io.BytesIO(storage.get_run(run_id, "depth.npz")))["depth"].astype(np.float32)
    except NotFound:
        raise HTTPException(404, "Run not found")
    rgb = _tex_base(aoi_id).copy()
    filled = np.nan_to_num(depth[min(max(hour, 1), depth.shape[0]) - 1], nan=-np.inf)
    band = sum(_smooth_mask(filled >= e, TEX_K).astype(np.int8) for e in DEPTH_EDGES) - 1
    for i, c in enumerate(DEPTH_COLORS):
        m = band == i
        rgb[m] = 0.2 * rgb[m] + 0.8 * np.array(_rgb(c))
    out = _jpeg(rgb)
    threading.Thread(target=storage.put_run, args=(run_id, key, out, "image/jpeg"), daemon=True).start()
    return Response(out, media_type="image/jpeg", headers=hdr)


_bld_mem: dict[str, bytes] = {}


def _buildings(aoi_id: str) -> bytes:
    """Cached (memory, then storage) only when non-empty: an area whose buildings arrive later must not stay empty."""
    if aoi_id in _bld_mem:
        return _bld_mem[aoi_id]
    data = _buildings_build(aoi_id)
    if data != b"[]":
        if len(_bld_mem) >= 4:
            _bld_mem.pop(next(iter(_bld_mem)))
        _bld_mem[aoi_id] = data
    return data


def _buildings_build(aoi_id: str) -> bytes:
    """[{i: index in buildings_proxy (= risk array index), p: [[x, y], ...] metre offsets, z: ground m, h: height m}]."""
    key = "bld3d_v2.json"
    try:
        return storage.get_bytes(aoi_id, key)
    except NotFound:
        pass
    grid = storage.load_grid(aoi_id)
    try:
        b = storage.load_gdf(aoi_id, "buildings_proxy.parquet")
    except NotFound:  # areas prepared before the building-class step
        return b"[]"
    b = b.to_crs(grid.crs) if str(b.crs) != str(grid.crs) else b
    dem = np.asarray(flow_ground(aoi_id)[0])
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
        out.append({"i": i, "p": pts, "z": round(float(z[i]), 1), "h": round(float(max(hgt[i], 2.5)), 1)})
    data = json.dumps(out, separators=(",", ":")).encode()
    if out:
        storage.put_bytes(aoi_id, key, data, "application/json")
    return data


@router.get("/api/aoi/{aoi_id}/3d/buildings.json")
def buildings(aoi_id: str, user: dict = Depends(require("viewer"))):
    """Open Buildings footprints on the flow ground (per area; risk comes per run from risk.bin)."""
    return Response(_buildings(aoi_id), media_type="application/json", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/api/runs/{run_id}/3d/risk.bin")
def building_risk(run_id: str, user: dict = Depends(require("viewer"))):
    """Estimated risk per building (uint8, 0 critical .. 3 low), indexed like buildings.json "i"."""
    try:
        risk = np.load(io.BytesIO(storage.get_run(run_id, "bld_risk.npy"))).astype(np.uint8)
    except NotFound:
        raise HTTPException(404, "No building risk for this run")
    return Response(risk.tobytes(), media_type="application/octet-stream", headers={"Cache-Control": "public, max-age=86400"})


MAJOR = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link"}
_ovl_mem: dict[str, bytes] = {}


def _overlays(run_id: str) -> bytes:
    """A run's roads, exit routes, used shelters and closing bridges in the 3D frame (metres from the grid centre)."""
    if run_id in _ovl_mem:
        return _ovl_mem[run_id]
    run = fs.get_doc("runs", run_id)
    if not run:
        raise HTTPException(404, "Unknown run")
    aoi_id = run.get("aoi_id") or (run.get("params") or {}).get("aoi_id")
    grid = storage.load_grid(aoi_id)
    from app.engines.grid import _to_utm
    t = _to_utm(grid.crs)
    W, H = grid.width * grid.cell, grid.height * grid.cell
    cx, cy = grid.x0 + W / 2, grid.y0 - H / 2

    def xy(lon, lat):
        x, y = t.transform(np.asarray(lon, float), np.asarray(lat, float))
        return np.round(np.asarray(x) - cx, 1), np.round(np.asarray(y) - cy, 1)

    def lines(fc: dict) -> list[tuple[dict, list]]:
        out = []
        for f in fc.get("features", []):
            g = f.get("geometry") or {}
            parts = [g["coordinates"]] if g.get("type") == "LineString" else g.get("coordinates", []) if g.get("type") == "MultiLineString" else []
            for c in parts:
                if len(c) < 2:
                    continue
                a = np.asarray(c, float)
                x, y = xy(a[:, 0], a[:, 1])
                out.append((f.get("properties") or {}, np.stack([x, y], 1).tolist()))
        return out

    def load(name: str) -> dict:
        try:
            return json.loads(storage.get_run(run_id, name))
        except NotFound:
            return {}

    roads = []
    for p, pts in lines(load("roads.geojson")):
        k = 0 if p.get("highway") in MAJOR else 1 if str(p.get("highway", "")).startswith("tertiary") else 2
        roads.append({"p": pts, "c": p.get("first_closed_hour"), "r": p.get("reason"), "h": p.get("hazard") or None,
                      "k": k, "n": p.get("name") or ""})
    routes = [{"p": pts, "until": p.get("passable_until_h"), "people": p.get("people", 0), "to": p.get("to_shelter"),
               "eta": p.get("eta_min")} for p, pts in lines(load("routes.geojson"))]
    shelters, bridges = [], []
    for s in run.get("shelters") or []:
        if (s.get("assigned") or 0) > 0:
            x, y = xy(s["lon"], s["lat"])
            shelters.append({"id": s["id"], "name": s.get("name", ""), "x": float(x), "y": float(y),
                             "people": s.get("assigned", 0), "capacity": s.get("capacity", 0)})
    for b in run.get("bridges") or []:
        if b.get("first_closed_hour") is not None:
            x, y = xy(b["lon"], b["lat"])
            bridges.append({"id": b["id"], "name": b.get("name", ""), "x": float(x), "y": float(y),
                            "c": b["first_closed_hour"], "r": b.get("reason")})
    data = gzip.compress(json.dumps({"roads": roads, "routes": routes, "shelters": shelters, "bridges": bridges},
                                    separators=(",", ":")).encode(), 6)
    _ovl_mem[run_id] = data
    return data


@router.get("/api/runs/{run_id}/3d/overlays.json")
def overlays(run_id: str, user: dict = Depends(require("viewer"))):
    """Roads with closure hour and blocked pieces, exit routes, used shelters and closing bridges, in metres from the
    3D grid centre (x east, y north), gzip-encoded. A run never changes, so it is cached."""
    return Response(_overlays(run_id), media_type="application/json",
                    headers={"Content-Encoding": "gzip", "Cache-Control": "public, max-age=86400"})
