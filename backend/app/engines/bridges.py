"""Bridges as real spans with a deck height (pure; no I/O).

OSMnx graph simplification merges each short bridge span into the roads on either side, so a graph edge tagged
`bridge` can be kilometres long. Spans therefore come from the OSM bridge ways themselves, and each span knows:
- its deck height above the normal river level, from HAND at its two ends (the abutments carry the road at deck
  level; the lower end is where water reaches the deck first);
- the modelled river reach it crosses (the reach of its lowest-HAND sample), or none for flyovers and gullies;
- whether OSM says it is under construction, disused or closed (closed from hour 1).
A span closes when the reach stage reaches its deck (minus an optional safety margin), never on a fixed stage.
"""
import math

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.ops import linemerge, unary_union
from shapely.strtree import STRtree

from app.engines.grid import GridSpec, xy_to_rowcol
from app.engines.roads import sample_cells

MIN_DECK_M = 3.0  # 30 m terrain cannot resolve a lower deck; below this the deck is set to this minimum
CROSSES_RIVER_HAND_M = 12.0  # a span whose lowest sample is higher than this above drainage is not over a modelled river
EXT_M = 10.0  # look this far beyond each end for the abutment (the end cell can straddle the bank)
DEDUPE_M = 30.0  # parallel carriageways of one bridge are one bridge
NEVER = 10**6


def _status(row) -> str:
    g = lambda k: (str(row.get(k)) if row.get(k) is not None and str(row.get(k)) not in ("<NA>", "nan", "None") else "")  # noqa: E731
    if g("highway") == "construction" or g("construction"):
        return "construction"
    if g("disused") in ("yes", "true") or g("abandoned") in ("yes", "true") or g("highway") in ("disused", "abandoned"):
        return "disused"
    if g("access") == "no":
        return "closed"
    return "open"


def _cell_value(arr: np.ndarray, grid: GridSpec, x: float, y: float) -> float:
    r, c = xy_to_rowcol(grid, x, y)
    if 0 <= r < grid.height and 0 <= c < grid.width:
        return float(arr[int(r), int(c)])
    return float("nan")


def _abutment_hand(line: LineString, hand: np.ndarray, grid: GridSpec, end: int) -> float:
    (x0, y0), (x1, y1) = (line.coords[0], line.coords[1]) if end == 0 else (line.coords[-1], line.coords[-2])
    d = math.hypot(x0 - x1, y0 - y1) or 1.0
    ux, uy = (x0 - x1) / d, (y0 - y1) / d  # outward
    vals = [_cell_value(hand, grid, x0, y0), _cell_value(hand, grid, x0 + ux * EXT_M, y0 + uy * EXT_M)]
    vals = [v for v in vals if np.isfinite(v)]
    return max(vals) if vals else float("nan")


def spans(ways, grid: GridSpec, hand: np.ndarray, reach_id: np.ndarray, dist_stream_m: np.ndarray | None = None,
          waterways=None) -> list[dict]:
    """ways: GeoDataFrame of OSM bridge ways in the grid CRS (osm.bridge_ways). Returns one dict per physical bridge.
    A span crosses a river only if it passes over a modelled stream cell (dist_stream_m <= one cell) or an OSM
    waterway (grid CRS geometries); flyovers over roads and railways never close on river stage."""
    wl = list(waterways) if waterways is not None else []  # built once (it was rebuilt for every candidate checked)
    wtree = STRtree(wl) if wl else None
    if ways is None or not len(ways):
        return []
    rows = ways.reset_index(drop=True)
    merged = linemerge(unary_union(list(rows.geometry)))  # a bridge mapped as several consecutive ways is one span
    lines = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    tree = STRtree(list(rows.geometry))
    out = []
    for ln in lines:
        if ln.length < 3:
            continue
        idx = [int(i) for i in tree.query(ln.buffer(1.0)) if rows.geometry.iloc[int(i)].within(ln.buffer(1.0))]
        parts = rows.iloc[idx] if idx else rows.iloc[[int(tree.nearest(ln))]]
        best = parts.iloc[int(np.argmax(parts.geometry.length.to_numpy()))]
        statuses = [_status(r) for _, r in parts.iterrows()]
        status = next((s for s in ("construction", "closed", "disused") if s in statuses), "open")
        names = [str(n) for n in parts["name"] if n is not None and str(n) not in ("<NA>", "nan", "None")]
        cells = sample_cells(ln, grid)
        h = hand.ravel()[cells] if cells else np.array([])
        finite = np.isfinite(h)
        low = int(np.argmin(np.where(finite, h, np.inf))) if finite.any() else -1
        rid = int(reach_id.ravel()[cells[low]]) if low >= 0 else -1
        over_stream = dist_stream_m is not None and len(cells) and float(np.nanmin(dist_stream_m.ravel()[cells])) <= grid.cell
        over_water = wtree is not None and any(ln.intersects(wl[int(i)]) for i in wtree.query(ln))
        if dist_stream_m is None and waterways is None:
            over_stream = True  # no evidence either way: trust HAND
        crosses = low >= 0 and h[low] <= CROSSES_RIVER_HAND_M and rid >= 0 and (over_stream or over_water)
        ends = [_abutment_hand(ln, hand, grid, 0), _abutment_hand(ln, hand, grid, -1)]
        ends = [e for e in ends if np.isfinite(e)]
        deck = min(ends) if ends else float("nan")
        deck_src = "terrain" if np.isfinite(deck) and deck >= MIN_DECK_M else "minimum"
        deck = max(deck, MIN_DECK_M) if np.isfinite(deck) else MIN_DECK_M
        mid = ln.interpolate(0.5, normalized=True)
        out.append({"osmid": str(best["osmid"]), "name": names[0] if names else "", "highway": str(best.get("highway") or ""),
                    "status": status, "length_m": round(float(ln.length), 1), "x": float(mid.x), "y": float(mid.y),
                    "deck_m": round(float(deck), 1), "deck_source": deck_src,
                    "reach": rid if crosses else -1, "cells": [int(c) for c in cells], "geometry": ln})
    # parallel carriageways: keep the longest span within DEDUPE_M
    out.sort(key=lambda s: -s["length_m"])
    kept = []
    for s in out:
        if any(math.hypot(s["x"] - k["x"], s["y"] - k["y"]) < DEDUPE_M and s["reach"] == k["reach"] for k in kept):
            continue
        kept.append(s)
    return kept


def link_edges(span_list: list[dict], edge_geoms) -> dict[int, list[int]]:
    """{edge row: [span index, ...]} for graph edges that run along a span (>= half the span's length within 5 m)."""
    if not span_list:
        return {}
    bufs = np.empty(len(span_list), object)
    bufs[:] = [s["geometry"].buffer(5.0) for s in span_list]
    geoms = np.empty(len(edge_geoms), object)
    geoms[:] = list(edge_geoms)
    links: dict[int, list[int]] = {}
    if not len(geoms):
        return links
    # every edge against the span tree in one query, then the overlap lengths in one call (was a query per edge)
    pe, pk = STRtree(list(bufs)).query(geoms)
    order = np.argsort(pe, kind="stable")  # per edge in the tree's own order, as the per-edge query gave them
    pe, pk = pe[order], pk[order]
    over = shapely.length(shapely.intersection(geoms[pe], bufs[pk]))
    need = np.array([0.5 * s["length_m"] for s in span_list])[pk]
    for e, k in zip(pe[over >= need], pk[over >= need]):
        links.setdefault(int(e), []).append(int(k))
    return links


def closure_hours(span_list: list[dict], stage: np.ndarray, margin_m: float = 0.0) -> tuple[np.ndarray, list[str], np.ndarray]:
    """(first closed hour 1-based or NEVER, reason, peak water level minus deck in m (NaN if not over a river)).
    stage: (R, H) reach stage above normal level, river offset already included. reason: construction / closed /
    disused (from OSM, hour 1) or "overtopped" (water at the deck minus margin)."""
    H = stage.shape[1] if stage.ndim == 2 else 0
    first = np.full(len(span_list), NEVER, np.int64)
    reason = [""] * len(span_list)
    over = np.full(len(span_list), np.nan)
    for k, s in enumerate(span_list):
        if s["status"] != "open":
            first[k], reason[k] = 1, s["status"]
            continue
        r = s["reach"]
        if r < 0 or s["deck_m"] is None or H == 0 or r >= stage.shape[0]:
            continue
        st = stage[r]
        over[k] = float(st.max()) - s["deck_m"]
        hit = np.flatnonzero(st >= s["deck_m"] - margin_m)
        if len(hit):
            first[k], reason[k] = int(hit[0]) + 1, "overtopped"
    return first, reason, over
