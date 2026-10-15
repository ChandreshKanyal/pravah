"""S2 hydrology on the native MERIT Hydro 3-arcsecond grid. Pure NumPy, no I/O.

All D8 work happens on the native grid (resampling D8 codes breaks connectivity); results are mapped
to the 30 m analysis grid at the end.
"""
import math
from collections import deque
from dataclasses import asdict, dataclass

import numpy as np

CELL_DEG = 1 / 1200  # 3 arc-seconds
DY_M = 92.66
D8_OFFSETS = {1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1), 16: (0, -1), 32: (-1, -1), 64: (-1, 0), 128: (-1, 1)}
REACH_MAX_M = 2000.0
SRC_STAGES = np.round(np.arange(0, 30.0001, 0.25), 2)


@dataclass(frozen=True)
class HydroGrid:
    lon0: float  # upper-left lon
    lat0: float  # upper-left lat
    width: int
    height: int
    cell_deg: float = CELL_DEG

    @property
    def lat_center(self) -> float:
        return self.lat0 - self.height * self.cell_deg / 2

    @property
    def dy(self) -> float:
        return DY_M

    @property
    def dx(self) -> float:
        return DY_M * math.cos(math.radians(self.lat_center))

    @property
    def cell_area(self) -> float:
        return self.dx * self.dy

    def to_dict(self) -> dict:
        return asdict(self)


def make_hydro_grid(bounds: tuple[float, float, float, float]) -> HydroGrid:
    """Snap (west, south, east, north) outward to multiples of 1/1200 degree."""
    w, s, e, n = bounds
    c0, c1 = math.floor(w * 1200), math.ceil(e * 1200)
    r0, r1 = math.floor(s * 1200), math.ceil(n * 1200)
    return HydroGrid(lon0=c0 / 1200, lat0=r1 / 1200, width=c1 - c0, height=r1 - r0)


def downstream_index(d8: np.ndarray) -> np.ndarray:
    """Flat index of each cell's downstream neighbour, or -1 (codes 0/-1/unknown, or leaving the grid)."""
    h, w = d8.shape
    rows, cols = np.indices((h, w))
    down = np.full(h * w, -1, np.int64)
    for code, (dr, dc) in D8_OFFSETS.items():
        m = d8 == code
        r2, c2 = rows[m] + dr, cols[m] + dc
        inside = (r2 >= 0) & (r2 < h) & (c2 >= 0) & (c2 < w)
        idx = np.flatnonzero(m.ravel())
        down[idx[inside]] = r2[inside] * w + c2[inside]
    return down


def local_accumulation_km2(downstream: np.ndarray, cell_area: float) -> np.ndarray:
    """Area inside the grid draining to each cell (incl. itself), via Kahn's topological order."""
    return accumulate(downstream, np.ones(downstream.size)) * cell_area / 1e6


def accumulate(downstream: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Sum of `weights` over each cell and everything upstream of it inside the grid (Kahn's order)."""
    n = downstream.size
    indeg = np.bincount(downstream[downstream >= 0], minlength=n)
    acc = np.asarray(weights, np.float64).ravel().copy()
    q = deque(np.flatnonzero(indeg == 0).tolist())
    while q:
        i = q.popleft()
        j = downstream[i]
        if j >= 0:
            acc[j] += acc[i]
            indeg[j] -= 1
            if indeg[j] == 0:
                q.append(j)
    return acc


def step_lengths(downstream: np.ndarray, grid: HydroGrid) -> np.ndarray:
    """Distance (m) from each cell to its downstream neighbour (0 where there is none)."""
    i = np.arange(downstream.size)
    j = np.where(downstream >= 0, downstream, i)
    dr = np.abs(j // grid.width - i // grid.width)
    dc = np.abs(j % grid.width - i % grid.width)
    return np.where((dr > 0) & (dc > 0), math.hypot(grid.dx, grid.dy),
                    np.where(dr > 0, grid.dy, np.where(dc > 0, grid.dx, 0.0)))


def flow_path(downstream: np.ndarray, grid: HydroGrid, elv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Longest flow path inside the grid ending at each cell: (length m, elevation of its head cell).

    Kirpich (1940) defines tc on the longest flow path L and its mean slope S = (z_head - z_outlet) / L.
    """
    n = downstream.size
    step = step_lengths(downstream, grid)
    z = np.nan_to_num(np.asarray(elv, np.float64).ravel())
    L = np.zeros(n)
    head = z.copy()
    indeg = np.bincount(downstream[downstream >= 0], minlength=n)
    q = deque(np.flatnonzero(indeg == 0).tolist())
    while q:
        i = q.popleft()
        j = downstream[i]
        if j >= 0:
            cand = L[i] + step[i]
            if cand > L[j]:
                L[j], head[j] = cand, head[i]
            indeg[j] -= 1
            if indeg[j] == 0:
                q.append(j)
    return L, head


def drain_cells(stream: np.ndarray, downstream: np.ndarray, max_iter: int = 20000) -> np.ndarray:
    """First stream cell reached by following downstream (flat index), -1 if none."""
    s = stream.ravel()
    t = np.where(s, np.arange(s.size), downstream)
    for _ in range(max_iter):
        move = (t != -1) & ~s[np.maximum(t, 0)]
        if not move.any():
            break
        t[move] = downstream[t[move]]
    return t


def _step_m(grid: HydroGrid, a: int, b: int) -> float:
    dr = abs(b // grid.width - a // grid.width)
    dc = abs(b % grid.width - a % grid.width)
    if dr and dc:
        return math.hypot(grid.dx, grid.dy)
    return grid.dy if dr else grid.dx


def n_upstream_stream(stream: np.ndarray, downstream: np.ndarray) -> np.ndarray:
    s = stream.ravel()
    src = np.flatnonzero(s & (downstream >= 0))
    src = src[s[downstream[src]]]
    return np.bincount(downstream[src], minlength=s.size)


def build_reaches(grid: HydroGrid, stream: np.ndarray, downstream: np.ndarray, elv: np.ndarray,
                  upa: np.ndarray, a_local: np.ndarray) -> tuple[np.ndarray, list[dict]]:
    """Split the stream network into reaches at sources, confluences, outlets and every 2 km."""
    s = stream.ravel()
    n_up = n_upstream_stream(stream, downstream)
    reach_id = np.full(s.size, -1, np.int32)
    heads = np.flatnonzero(s & (n_up != 1))
    elv_f, upa_f = elv.ravel(), upa.ravel()
    reaches: list[dict] = []

    def close(cells: list[int], length: float) -> None:
        rid = len(reaches)
        reach_id[cells] = rid
        e_up, e_down = float(elv_f[cells[0]]), float(elv_f[cells[-1]])
        L = max(length, grid.dx)
        last = cells[-1]
        mid = cells[len(cells) // 2]
        reaches.append({
            "reach_id": rid, "L_m": L, "e_up": e_up, "e_down": e_down,
            "S": float(np.clip((e_up - e_down) / L, 0.001, 0.5)),
            "A_up_km2": float(upa_f[last]), "A_loc_km2": float(a_local[last]),
            "cells": [int(c) for c in cells],
            "centroid_lonlat": [grid.lon0 + (mid % grid.width + 0.5) * grid.cell_deg,
                                grid.lat0 - (mid // grid.width + 0.5) * grid.cell_deg],
        })

    for h in heads:
        cells, length, cur = [int(h)], 0.0, int(h)
        while True:
            nxt = int(downstream[cur])
            if nxt < 0 or not s[nxt] or n_up[nxt] != 1 or reach_id[nxt] >= 0:
                close(cells, length)
                break
            step = _step_m(grid, cur, nxt)
            if length + step >= REACH_MAX_M:
                close(cells, length)
                cells, length = [nxt], 0.0
            else:
                cells.append(nxt)
                length += step
            cur = nxt
    return reach_id, reaches


def local_slope(elv: np.ndarray, grid: HydroGrid) -> np.ndarray:
    gy, gx = np.gradient(elv.astype(np.float64), grid.dy, grid.dx)
    return np.hypot(gx, gy)


def src_point(hand: np.ndarray, cell_area: float, slope: np.ndarray, h: float, L: float, S: float, n: float) -> dict:
    """Zheng et al. (2018) synthetic rating curve at one stage h for one reach's catchment cells."""
    wet = hand < h
    V = float(np.sum((h - hand[wet]) * cell_area))
    A_b = float(np.sum(cell_area * np.sqrt(1 + slope[wet] ** 2)))
    A, P = V / L, A_b / L
    R = A / P if P > 0 else 0.0
    Q = A * R ** (2 / 3) * math.sqrt(S) / n
    return {"V": V, "A_b": A_b, "A": A, "P": P, "R": R, "Q": Q}


def src_tables(hand: np.ndarray, catch_reach: np.ndarray, slope: np.ndarray, reaches: list[dict],
               cell_area: float, n: float = 0.04) -> dict[str, dict]:
    """{reach_id: {"h": [...], "Q": [...]}} with Q monotone non-decreasing and Q(0) = 0."""
    hf, cr, sf = hand.ravel(), catch_reach.ravel(), slope.ravel()
    order = np.argsort(cr, kind="stable")
    bounds = np.searchsorted(cr[order], np.arange(len(reaches) + 1))
    out = {}
    for r in reaches:
        rid = r["reach_id"]
        idx = order[bounds[rid]:bounds[rid + 1]]
        hv, sv = hf[idx], sf[idx]
        ok = np.isfinite(hv)
        hv, sv = hv[ok], sv[ok]
        depth = np.clip(SRC_STAGES[:, None] - hv[None, :], 0, None)  # (stages, cells)
        wet = depth > 0
        V = depth.sum(axis=1) * cell_area
        A_b = (wet * np.sqrt(1 + sv[None, :] ** 2)).sum(axis=1) * cell_area
        A, P = V / r["L_m"], A_b / r["L_m"]
        R = np.divide(A, P, out=np.zeros_like(A), where=P > 0)
        Q = np.maximum.accumulate(A * R ** (2 / 3) * math.sqrt(r["S"]) / n)
        Q[0] = 0.0
        out[str(rid)] = {"h": SRC_STAGES.tolist(), "Q": Q.round(3).tolist()}
    return out


def src_stage(table: dict, Q: float) -> float:
    """Stage (m) for discharge Q from a reach's SRC table, clipped to [0, 30]."""
    if not Q > 0:
        return 0.0
    q = np.asarray(table["Q"])
    h = np.asarray(table["h"])
    # flat leading section: interp needs strictly increasing xp to be meaningful; use the last h at each Q
    q_u, last = np.unique(q[::-1], return_index=True)
    h_u = h[::-1][last]
    return float(np.clip(np.interp(Q, q_u, h_u), 0, 30))


def hotspots(grid: HydroGrid, stream: np.ndarray, downstream: np.ndarray, upa: np.ndarray, top: int = 15) -> list[dict]:
    """Confluences (>= 2 upstream stream cells) and surges (upa +50% over the largest upstream stream neighbour)."""
    s, upa_f = stream.ravel(), upa.ravel()
    n_up = n_upstream_stream(stream, downstream)
    src = np.flatnonzero(s & (downstream >= 0))
    src = src[s[downstream[src]]]
    max_up = np.zeros(s.size)
    np.maximum.at(max_up, downstream[src], upa_f[src])
    conf = s & (n_up >= 2)
    surge = s & (n_up >= 1) & (upa_f > 1.5 * max_up) & ~conf
    cand = [(float(upa_f[i]), int(i), "confluence") for i in np.flatnonzero(conf)]
    cand += [(float(upa_f[i]), int(i), "surge") for i in np.flatnonzero(surge)]
    cand.sort(reverse=True)
    out = []
    for k, (a, i, kind) in enumerate(cand[:top], start=1):
        out.append({"id": f"H{k}", "lon": grid.lon0 + (i % grid.width + 0.5) * grid.cell_deg,
                    "lat": grid.lat0 - (i // grid.width + 0.5) * grid.cell_deg, "upa_km2": round(a, 1), "type": kind})
    return out


def hydro_index_for_lonlat(grid: HydroGrid, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Flat native index for each lon/lat, -1 if outside."""
    col = np.floor((lon - grid.lon0) / grid.cell_deg).astype(np.int64)
    row = np.floor((grid.lat0 - lat) / grid.cell_deg).astype(np.int64)
    inside = (row >= 0) & (row < grid.height) & (col >= 0) & (col < grid.width)
    return np.where(inside, row * grid.width + col, -1)
