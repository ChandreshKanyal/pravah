"""S13 urban pluvial ponding screening. Pure NumPy/SciPy; screening, not hydrodynamic modelling.

1. Priority-Flood + epsilon (Barnes, Lehman & Mulla 2014) gives the depression-filled DEM; dep_depth = filled - dem.
2. D8 on the filled surface routes every cell to the first depression on its path (its watershed).
3. Per hour, each depression receives V_in = C_ws * excess rain * A_ws and fills from the bottom to the water level
   that holds V_in, capped at its spill level (fill-spill without merging).

NOTE(spec-drift): the spec scaled depth uniformly (dep_depth * fill); filling to a level is the standard volume-
conserving approach. Rain is reduced by the storm-drain design capacity (config), as drains remove it first.
"""
import heapq
import math

import numpy as np
from scipy import ndimage

from app.engines.hydrology import accumulate, drain_cells

EPS = 1e-4  # m; makes filled flats drain (epsilon variant)
MIN_DEP_M = 0.05
_OFFS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def priority_flood(dem: np.ndarray, eps: float = EPS) -> np.ndarray:
    """Depression-filled DEM. Edge cells and NaN cells are outlets."""
    z = np.asarray(dem, dtype=np.float64)
    h, w = z.shape
    filled = np.where(np.isfinite(z), z, -np.inf)
    closed = np.zeros((h, w), bool)
    heap: list[tuple[float, int]] = []
    edge = np.zeros((h, w), bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    edge |= ~np.isfinite(z)
    for i in np.flatnonzero(edge):
        r, c = divmod(int(i), w)
        closed[r, c] = True
        heapq.heappush(heap, (filled[r, c], int(i)))
    while heap:
        zc, i = heapq.heappop(heap)
        r, c = divmod(i, w)
        for dr, dc in _OFFS:
            rr, cc = r + dr, c + dc
            if 0 <= rr < h and 0 <= cc < w and not closed[rr, cc]:
                closed[rr, cc] = True
                if filled[rr, cc] <= zc:
                    filled[rr, cc] = zc + eps
                heapq.heappush(heap, (filled[rr, cc], rr * w + cc))
    return np.where(np.isfinite(z), filled, np.nan)


def d8_downstream(filled: np.ndarray, cell: float) -> np.ndarray:
    """Flat index of the steepest-descent neighbour on the filled surface, -1 at outlets."""
    h, w = filled.shape
    z = np.where(np.isfinite(filled), filled, -1e9)
    best = np.zeros((h, w))
    down = np.full((h, w), -1, np.int64)
    rows, cols = np.indices((h, w))
    pad = np.pad(z, 1, constant_values=np.inf)
    for dr, dc in _OFFS:
        nb = pad[1 + dr:1 + dr + h, 1 + dc:1 + dc + w]
        slope = (z - nb) / (cell * math.hypot(dr, dc))
        better = slope > best
        best = np.where(better, slope, best)
        down = np.where(better, (rows + dr) * w + (cols + dc), down)
    return down.ravel()


def prepare(dem: np.ndarray, cell: float, runoff_c: np.ndarray) -> dict:
    """Static depression analysis for an urban AOI (run once in prepare_area)."""
    filled = priority_flood(dem)
    dep = np.nan_to_num(filled - dem, nan=0.0)
    down = d8_downstream(filled, cell)
    acc = accumulate(down, np.ones(down.size)).reshape(dem.shape)
    lab, n = ndimage.label(dep > MIN_DEP_M, structure=np.ones((3, 3)))
    first = drain_cells((lab > 0), down)
    ws = np.where(first >= 0, lab.ravel()[np.maximum(first, 0)], 0)
    a = cell * cell
    C = np.where(np.isfinite(runoff_c), runoff_c, np.nanmean(runoff_c) if np.isfinite(runoff_c).any() else 0.6).ravel()
    ws_cells = np.bincount(ws, minlength=n + 1)
    c_ws = np.bincount(ws, weights=C, minlength=n + 1) / np.maximum(ws_cells, 1)
    order = np.argsort(lab.ravel(), kind="stable")
    bounds = np.searchsorted(lab.ravel()[order], np.arange(n + 2))
    z_sorted, offsets, v_dep, spill = [], [0], np.zeros(n + 1), np.zeros(n + 1)
    zf = np.asarray(dem, np.float64).ravel()
    for k in range(1, n + 1):
        idx = order[bounds[k]:bounds[k + 1]]
        zs = np.sort(zf[idx])
        z_sorted.append(zs)
        offsets.append(offsets[-1] + len(zs))
        v_dep[k] = float(dep.ravel()[idx].sum() * a)
        spill[k] = float(np.nanmax(filled.ravel()[idx]))
    return {"filled": filled.astype(np.float32), "dep_depth": dep.astype(np.float32), "dep_label": lab.astype(np.int32),
            "ws_label": ws.reshape(dem.shape).astype(np.int32), "acc_cells": acc.astype(np.float32),
            "ws_area_m2": (ws_cells * a).astype(np.float64), "c_ws": c_ws, "v_dep": v_dep, "spill": spill,
            "z_sorted": np.concatenate(z_sorted) if z_sorted else np.zeros(0), "z_offsets": np.asarray(offsets, np.int64)}


def level_for_volume(z_sorted: np.ndarray, V: float, a: float, spill: float) -> float:
    """Water level that holds volume V (m3) over cells with sorted ground elevations, capped at the spill level."""
    if V <= 0 or not len(z_sorted):
        return -np.inf
    cs = np.cumsum(z_sorted)
    j_all = np.arange(1, len(z_sorted) + 1)
    vb = a * (j_all * z_sorted - cs)  # volume when the level reaches z_sorted[j]
    j = max(0, int(np.searchsorted(vb, V, side="right")) - 1)
    return float(min((V / a + cs[j]) / (j + 1), spill))


def ponding(static: dict, dem: np.ndarray, rain_mm_h, cell: float, drain_capacity_mm_h: float = 25.0) -> tuple[np.ndarray, np.ndarray]:
    """(ponding depth [H, rows, cols], fill fraction [H, n_dep + 1]) for an hourly rain series."""
    i = np.asarray(rain_mm_h, dtype=float)
    excess = np.cumsum(np.clip(i - drain_capacity_mm_h, 0, None))  # mm beyond what the drains carry
    lab = static["dep_label"]
    n = len(static["v_dep"]) - 1
    a = cell * cell
    flat = lab.ravel()
    order = np.argsort(flat, kind="stable")
    bounds = np.searchsorted(flat[order], np.arange(n + 2))
    zf = np.asarray(dem, np.float64).ravel()
    out = np.zeros((len(i),) + lab.shape, np.float32)
    fill = np.zeros((len(i), n + 1))
    v_in_all = static["c_ws"] * static["ws_area_m2"]  # m3 per metre of excess rain
    for t, P in enumerate(excess):
        if P <= 0:
            continue
        o = out[t].ravel()
        for k in range(1, n + 1):
            V = min(v_in_all[k] * P / 1000.0, static["v_dep"][k])
            if V <= 0 or static["v_dep"][k] <= 0:
                continue
            fill[t, k] = V / static["v_dep"][k]
            zs = static["z_sorted"][static["z_offsets"][k - 1]:static["z_offsets"][k]]
            L = level_for_volume(zs, V, a, static["spill"][k])
            idx = order[bounds[k]:bounds[k + 1]]
            o[idx] = np.clip(L - zf[idx], 0, None)
        out[t] = o.reshape(lab.shape)
    return out, fill


def likelihood_class(fill_frac: np.ndarray, dep_label: np.ndarray) -> np.ndarray:
    """Per-cell ponding likelihood at one hour: 0 none, 1 low, 2 medium (fill >= 0.3), 3 high (fill >= 0.7)."""
    f = np.asarray(fill_frac)[dep_label]
    cls = np.where(f >= 0.7, 3, np.where(f >= 0.3, 2, np.where(f > 0, 1, 0)))
    return np.where(dep_label > 0, cls, 0).astype(np.uint8)
