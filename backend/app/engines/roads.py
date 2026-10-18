"""Road graph preparation (S7.1-S7.4, S9.3): per-edge sample cells, travel time and static attributes."""
import math

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import shapely
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


# Typical free-flow speeds (km/h) by road class, used only when no road in the area has a mapped speed limit (OSMnx
# then has nothing to average; e.g. Puri, 18 Oct). Planning assumptions for Indian roads, not measured; links take
# their road's speed.
DEFAULT_KPH = {"motorway": 80, "trunk": 60, "primary": 50, "secondary": 40, "tertiary": 30, "unclassified": 25,
               "residential": 20, "living_street": 10, "service": 15, "road": 25}
DEFAULT_KPH |= {f"{k}_link": v for k, v in DEFAULT_KPH.items()}
FALLBACK_KPH = 25


def add_speeds(G):
    """OSMnx speeds from mapped speed limits (mean per road class); when no edge has one, DEFAULT_KPH."""
    try:
        return ox.add_edge_speeds(G)
    except ValueError:
        return ox.add_edge_speeds(G, hwy_speeds=DEFAULT_KPH, fallback=FALLBACK_KPH)


def tobler_kmh(tan_theta):
    """Tobler (1993) hiking speed: 6 * exp(-3.5 * |tan + 0.05|) km/h."""
    return 6 * np.exp(-3.5 * np.abs(np.asarray(tan_theta, dtype=float) + 0.05))


# OSMnx keeps the values of road segments merged by graph simplification as list(set(values)), whose order changes from
# one process to the next (string hashing is randomised): taking "the first" made the same area prepare differently
# each time (18 Oct: 45 of 23,000 edges changed road class between two preparations). Lists resolve by fixed rules:
# the most important road class, the first name in alphabetical order, the widest lanes and width, a bridge if any
# merged segment is one.
HIGHWAY_RANK = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "road",
                "living_street", "service", "track", "pedestrian", "cycleway", "path", "footway", "steps"]


def _first(v):
    return sorted(v, key=str)[0] if isinstance(v, list) and v else v


def highway_class(v) -> str:
    if isinstance(v, list) and v:
        rank = lambda h: HIGHWAY_RANK.index(str(h).removesuffix("_link")) if str(h).removesuffix("_link") in HIGHWAY_RANK else len(HIGHWAY_RANK)  # noqa: E731
        v = min(v, key=lambda h: (rank(h), str(h)))
    return str(v)


def _num(v) -> float:
    vals = v if isinstance(v, list) else [v]
    out = float("nan")
    for x in vals:
        try:
            f = float(str(x).split(";")[0].replace("m", "").strip())
        except (TypeError, ValueError):
            continue
        out = f if not out >= f else out  # the largest value (NaN never wins)
    return out


def is_bridge(v) -> bool:
    if isinstance(v, list):
        return any(is_bridge(x) for x in v)
    return v is not None and str(v).lower() not in ("no", "none", "nan", "false", "0", "")


def narrowness(highway, lanes, width) -> float:
    n = NARROWNESS.get(highway_class(highway), 0.6)
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


def tobler_time_s(geom: LineString, grid: GridSpec, dem: np.ndarray, start_xy: tuple[float, float],
                  length_m: float) -> float:
    """Walking time along the line, Tobler speed per ~30 m segment from DEM samples (captures climbs and descents
    that cancel out between the end nodes). The geometry is oriented to start at `start_xy`; time is scaled to the
    OSM length."""
    L = geom.length
    if L <= 0:
        return length_m / (float(tobler_kmh(0.0)) / 3.6)
    c0 = geom.coords[0]
    if math.hypot(c0[0] - start_xy[0], c0[1] - start_xy[1]) > math.hypot(geom.coords[-1][0] - start_xy[0],
                                                                         geom.coords[-1][1] - start_xy[1]):
        geom = LineString(list(geom.coords)[::-1])
    d = np.append(np.arange(0, L, SAMPLE_M), L)
    pts = [geom.interpolate(x) for x in d]
    r, c = xy_to_rowcol(grid, [p.x for p in pts], [p.y for p in pts])
    r = np.clip(r, 0, grid.height - 1)
    c = np.clip(c, 0, grid.width - 1)
    z = np.asarray(dem, dtype=float)[r, c]
    seg = np.diff(d)
    ok = seg > 0
    if not ok.any():
        return length_m / (float(tobler_kmh(0.0)) / 3.6)
    dz = np.nan_to_num(np.diff(z))
    t = float(np.sum(seg[ok] / (tobler_kmh(dz[ok] / seg[ok]) / 3.6)))
    return t * (length_m / L)


def _samples(geoms: np.ndarray, L: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For every line at once: the distances np.append(np.arange(0, L, 30), L) ([0] for a zero-length line) flattened,
    each line's offset into them, and the sample points' x, y (one vectorized GEOS call instead of one per point)."""
    n = np.where(L > 0, np.ceil(L / SAMPLE_M).astype(np.int64) + 1, 1)
    starts = np.zeros(len(L) + 1, np.int64)
    np.cumsum(n, out=starts[1:])
    owner = np.repeat(np.arange(len(L)), n)
    d = (np.arange(starts[-1]) - starts[:-1][owner]) * SAMPLE_M
    d[starts[1:] - 1] = np.where(L > 0, L, 0.0)
    xy = shapely.get_coordinates(shapely.line_interpolate_point(geoms[owner], d))
    return d, starts, xy


def edge_table(G: nx.MultiDiGraph, grid: GridSpec, mode: str, dem: np.ndarray, slope_deg: np.ndarray) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """G must be projected to the grid CRS; for drive it must carry `travel_time` (OSMnx). Returns (edges, nodes).
    Sample cells and walking times come from all the edges' sample points at once (18 Oct; per-edge interpolation
    took ~5 s of a 15 s network step); results are the same as sample_cells and tobler_time_s per edge."""
    nodes = {n: (d["x"], d["y"]) for n, d in G.nodes(data=True)}
    nid = list(nodes)
    nx_, ny_ = np.array([nodes[n][0] for n in nid]), np.array([nodes[n][1] for n in nid])
    steep = (maximum_filter(np.nan_to_num(slope_deg), size=3) >= 35).ravel()
    recs = list(G.edges(keys=True, data=True))
    geoms = np.empty(len(recs), object)
    geoms[:] = [d.get("geometry") or LineString([nodes[u], nodes[v]]) for u, v, k, d in recs]
    L = shapely.length(geoms) if len(recs) else np.zeros(0)
    d_all, starts, xy = _samples(geoms, L)
    r = np.floor((grid.y0 - xy[:, 1]) / grid.cell).astype(int)
    c = np.floor((xy[:, 0] - grid.x0) / grid.cell).astype(int)
    ok = (r >= 0) & (r < grid.height) & (c >= 0) & (c < grid.width)
    flat = r * grid.width + c
    walk_t = _tobler_times(recs, geoms, L, d_all, starts, xy, nodes, grid, dem) if mode == "walk" else None
    rows = []
    for i, (u, v, k, d) in enumerate(recs):
        geom = geoms[i]
        s0, s1 = starts[i], starts[i + 1]
        cells = list(dict.fromkeys(int(f) for f in flat[s0:s1][ok[s0:s1]]))
        length = float(d.get("length", L[i])) or L[i] or 1.0
        if mode == "walk":
            t0 = walk_t[i] * (length / L[i]) if L[i] > 0 and np.isfinite(walk_t[i]) else length / (float(tobler_kmh(0.0)) / 3.6)
        else:
            t0 = float(d.get("travel_time", length / (30 / 3.6)))
        rows.append({
            "u": u, "v": v, "key": k, "geometry": geom, "length_m": length, "t0_s": t0,
            "bridge": is_bridge(d.get("bridge")), "cells": cells, "name": str(_first(d.get("name", "")) or ""),
            "highway": highway_class(d.get("highway", "")),
            "slope_adjacent": bool(steep[cells].any()) if cells else False,
            "narrowness": narrowness(d.get("highway"), d.get("lanes"), d.get("width")),
        })
    edges = gpd.GeoDataFrame(rows, geometry="geometry", crs=grid.crs)
    node_df = gpd.GeoDataFrame({"node": nid, "x": nx_, "y": ny_}, geometry=gpd.points_from_xy(nx_, ny_), crs=grid.crs)
    ll = node_df.to_crs("EPSG:4326")
    node_df["lon"], node_df["lat"] = ll.geometry.x.to_numpy(), ll.geometry.y.to_numpy()
    return edges, node_df


def _tobler_times(recs, geoms, L, d_all, starts, xy, nodes, grid, dem) -> np.ndarray:
    """tobler_time_s for every edge before the scaling to the OSM length (NaN = no segment: flat-speed fallback)."""
    E = len(recs)
    # orient each line to start at its edge's first node (as tobler_time_s does); reversed lines are sampled again
    rev = np.zeros(E, bool)
    for i, (u, _v, _k, _d) in enumerate(recs):
        if L[i] > 0:
            cs = geoms[i].coords
            sx, sy = nodes[u]
            rev[i] = math.hypot(cs[0][0] - sx, cs[0][1] - sy) > math.hypot(cs[-1][0] - sx, cs[-1][1] - sy)
    xy = xy.copy()
    if rev.any():
        owner = np.repeat(np.arange(E), np.diff(starts))
        sel = rev[owner]
        xy[sel] = shapely.get_coordinates(shapely.line_interpolate_point(shapely.reverse(geoms[owner[sel]]), d_all[sel]))
    r = np.clip(np.floor((grid.y0 - xy[:, 1]) / grid.cell).astype(int), 0, grid.height - 1)
    c = np.clip(np.floor((xy[:, 0] - grid.x0) / grid.cell).astype(int), 0, grid.width - 1)
    z = np.asarray(dem, dtype=float)[r, c]
    out = np.full(E, np.nan)
    for i in range(E):  # per-edge sums, as tobler_time_s computes them
        if L[i] <= 0:
            continue
        s0, s1 = starts[i], starts[i + 1]
        seg = np.diff(d_all[s0:s1])
        okk = seg > 0
        if not okk.any():
            continue
        dz = np.nan_to_num(np.diff(z[s0:s1]))
        out[i] = float(np.sum(seg[okk] / (tobler_kmh(dz[okk] / seg[okk]) / 3.6)))
    return out


def walk_speed_kmh_flat() -> float:
    return float(tobler_kmh(0.0))


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))
