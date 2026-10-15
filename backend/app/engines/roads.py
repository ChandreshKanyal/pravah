"""Road graph preparation (S7.1-S7.4, S9.3): per-edge sample cells, travel time and static attributes."""
import math

import geopandas as gpd
import networkx as nx
import numpy as np
from scipy.ndimage import maximum_filter
from shapely.geometry import LineString

from app.engines.grid import xy_to_rowcol
from app.models.grid import GridSpec

SAMPLE_M = 30.0
NARROWNESS = {
    "footway": 1.0, "path": 1.0, "steps": 1.0, "pedestrian": 1.0, "track": 1.0, "cycleway": 1.0,
    "living_street": 0.8, "service": 0.8,
    "residential": 0.6, "unclassified": 0.6, "road": 0.6,
    "tertiary": 0.4, "tertiary_link": 0.4,
    "secondary": 0.3, "secondary_link": 0.3,
    "primary": 0.2, "primary_link": 0.2, "trunk": 0.2, "trunk_link": 0.2, "motorway": 0.2,
}


def tobler_kmh(tan_theta):
    """Tobler (1993) hiking speed: 6 * exp(-3.5 * |tan + 0.05|) km/h."""
    return 6 * np.exp(-3.5 * np.abs(np.asarray(tan_theta, dtype=float) + 0.05))


def _first(v):
    return v[0] if isinstance(v, list) else v


def _num(v) -> float:
    v = _first(v)
    try:
        return float(str(v).split(";")[0].replace("m", "").strip())
    except (TypeError, ValueError):
        return float("nan")


def is_bridge(v) -> bool:
    v = _first(v)
    return v is not None and str(v).lower() not in ("no", "none", "nan", "false", "0", "")


def narrowness(highway, lanes, width) -> float:
    n = NARROWNESS.get(str(_first(highway)), 0.6)
    if _num(lanes) >= 2 or _num(width) >= 7:
        n -= 0.1
    return float(np.clip(n, 0, 1))


def sample_cells(geom: LineString, grid: GridSpec) -> list[int]:
    """Flat grid indices of points every 30 m along the line (start and end included), in order, unique."""
    L = geom.length
    d = np.append(np.arange(0, L, SAMPLE_M), L) if L > 0 else np.array([0.0])
    pts = [geom.interpolate(x) for x in d]
    r, c = xy_to_rowcol(grid, [p.x for p in pts], [p.y for p in pts])
    ok = (r >= 0) & (r < grid.height) & (c >= 0) & (c < grid.width)
    flat = (r[ok] * grid.width + c[ok]).tolist()
    return list(dict.fromkeys(int(f) for f in flat))


def edge_table(G: nx.MultiDiGraph, grid: GridSpec, mode: str, dem: np.ndarray, slope_deg: np.ndarray,
               lsi_class: np.ndarray | None) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """G must be projected to the grid CRS; for drive it must carry `travel_time` (OSMnx). Returns (edges, nodes)."""
    nodes = {n: (d["x"], d["y"]) for n, d in G.nodes(data=True)}
    nid = list(nodes)
    nx_, ny_ = np.array([nodes[n][0] for n in nid]), np.array([nodes[n][1] for n in nid])
    nr, nc = xy_to_rowcol(grid, nx_, ny_)
    inside = (nr >= 0) & (nr < grid.height) & (nc >= 0) & (nc < grid.width)
    z = {n: float(dem[nr[i], nc[i]]) if inside[i] else np.nan for i, n in enumerate(nid)}
    steep = maximum_filter(np.nan_to_num(slope_deg), size=3) >= 35
    lsi_f = lsi_class.ravel() if lsi_class is not None else None
    rows = []
    for u, v, k, d in G.edges(keys=True, data=True):
        geom = d.get("geometry") or LineString([nodes[u], nodes[v]])
        cells = sample_cells(geom, grid)
        length = float(d.get("length", geom.length)) or geom.length or 1.0
        if mode == "walk":
            dz = z[v] - z[u]
            tan = dz / length if np.isfinite(dz) else 0.0
            t0 = length / (float(tobler_kmh(tan)) / 3.6)
        else:
            t0 = float(d.get("travel_time", length / (30 / 3.6)))
        rows.append({
            "u": u, "v": v, "key": k, "geometry": geom, "length_m": length, "t0_s": t0,
            "bridge": is_bridge(d.get("bridge")), "cells": cells, "name": str(_first(d.get("name", "")) or ""),
            "highway": str(_first(d.get("highway", ""))),
            "lsi_static_max": int(max((lsi_f[c] for c in cells), default=0)) if lsi_f is not None else 0,
            "slope_adjacent": bool(any(steep.ravel()[c] for c in cells)),
            "narrowness": narrowness(d.get("highway"), d.get("lanes"), d.get("width")),
        })
    edges = gpd.GeoDataFrame(rows, geometry="geometry", crs=grid.crs)
    node_df = gpd.GeoDataFrame({"node": nid, "x": nx_, "y": ny_}, geometry=gpd.points_from_xy(nx_, ny_), crs=grid.crs)
    ll = node_df.to_crs("EPSG:4326")
    node_df["lon"], node_df["lat"] = ll.geometry.x.to_numpy(), ll.geometry.y.to_numpy()
    return edges, node_df


def walk_speed_kmh_flat() -> float:
    return float(tobler_kmh(0.0))


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))
