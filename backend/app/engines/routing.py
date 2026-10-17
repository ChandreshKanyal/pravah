"""Evacuation routing with capacity-aware assignment (S8). Pure NetworkX/NumPy, no I/O."""
import math

import networkx as nx
import numpy as np
from scipy import ndimage

NEVER = 10**6  # first_closed_hour sentinel
OVERFLOW_COST = 10_000_000
WALK_FLAT_KMH = 6 * math.exp(-3.5 * 0.05)  # Tobler on flat ground, 5.04 km/h


def edge_states(cells: list[list[int]], blocked: np.ndarray, depth: np.ndarray, depth_limit_m: float,
                bridge_first: np.ndarray | None = None, bridge_cells: list[set] | None = None) -> tuple[np.ndarray, list[str]]:
    """first_closed_hour (1-based, NEVER if open) and reason per edge.

    Bridges (engines/bridges.py) close only when OSM marks them under construction/closed or the river reaches their
    deck; `bridge_first[e]` is the first such hour for the spans edge e runs over (NEVER if none). The cells over a span
    (`bridge_cells[e]`) are left out of the flood test: they lie above the water.
    """
    H = depth.shape[0]
    d_flat = depth.reshape(H, -1)
    E = len(cells)
    first = np.full(E, NEVER, np.int64)
    reason = [""] * E
    for e, c in enumerate(cells):
        if blocked[e]:
            first[e], reason[e] = 1, "blocked"
            continue
        if not c:
            continue
        if bridge_cells is not None and bridge_cells[e]:
            c = [x for x in c if x not in bridge_cells[e]]
        bf = int(bridge_first[e]) if bridge_first is not None else NEVER
        if not c:
            if bf < NEVER:
                first[e], reason[e] = bf, "bridge"
            continue
        dc = np.nan_to_num(d_flat[:, c])  # NaN = permanent river, not flood
        bridge_now = np.arange(1, H + 1) >= bf
        causes = [("bridge", bridge_now), ("flood", dc.max(axis=1) > depth_limit_m)]
        for t in range(H):
            hit = [name for name, m in causes if m[t]]
            if hit:
                first[e], reason[e] = t + 1, hit[0]
                break
    return first, reason


def edge_weight(t0_s, crowd_e, slope_adjacent) -> np.ndarray:
    """w = t0 x (1 + 0.3 crowd) x (1.2 if steep slope beside the road)."""
    return np.asarray(t0_s) * (1 + 0.3 * np.asarray(crowd_e)) * np.where(np.asarray(slope_adjacent), 1.2, 1.0)


def build_graph(u, v, w, open_mask) -> nx.DiGraph:
    """Directed graph of open edges, keeping the cheapest of parallel edges; edge attr `e` = edge row index."""
    G = nx.DiGraph()
    for i in np.flatnonzero(open_mask):
        a, b, wi = u[i], v[i], float(w[i])
        if not G.has_edge(a, b) or G[a][b]["w"] > wi:
            G.add_edge(a, b, w=wi, e=int(i))
    return G


def travel_times(G: nx.DiGraph, shelter_nodes: dict[str, int], cutoff_s: float) -> dict[str, dict]:
    """{shelter_id: {node: seconds to reach the shelter}} via Dijkstra on the reversed graph."""
    R = G.reverse(copy=False)
    out = {}
    for sid, node in shelter_nodes.items():
        out[sid] = nx.single_source_dijkstra_path_length(R, node, weight="w", cutoff=cutoff_s) if node in G else {}
    return out


def transport_solve(demand: dict, capacity: dict[str, int], times: dict[str, dict]) -> tuple[dict, int, int]:
    """Min total travel time assignment (network simplex) with an always-feasible overflow edge.
    Returns ({(node, sid): people}, capacity_gap, total_cost_of_placed_people)."""
    total = int(sum(demand.values()))
    G = nx.DiGraph()
    G.add_node("T", demand=total)
    for sid, cap in capacity.items():
        G.add_node(f"S:{sid}", demand=0)
        G.add_edge(f"S:{sid}", "T", capacity=int(cap), weight=0)
    for node, people in demand.items():
        d = f"D:{node}"
        G.add_node(d, demand=-int(people))
        G.add_edge(d, "T", weight=OVERFLOW_COST)
        for sid in capacity:
            if node in times.get(sid, {}):
                G.add_edge(d, f"S:{sid}", weight=int(round(times[sid][node])))
    if total == 0:
        return {}, 0, 0
    _, flow = nx.network_simplex(G)
    alloc, gap, cost = {}, 0, 0
    for d, outs in flow.items():
        if not d.startswith("D:"):
            continue
        node = demand_key(d[2:], demand)
        for tgt, f in outs.items():
            if f <= 0:
                continue
            if tgt == "T":
                gap += f
            else:
                sid = tgt[2:]
                alloc[(node, sid)] = f
                cost += f * int(round(times[sid][node]))
    return alloc, gap, cost


def demand_key(s: str, demand: dict):
    """Recover the original node key (ints stay ints) from its string form."""
    for k in demand:
        if str(k) == s:
            return k
    return s


def assembly_points(max_depth: np.ndarray, hand: np.ndarray, slope_deg: np.ndarray,
                    dist_road_m: np.ndarray, cell: float, top: int = 10) -> list[dict]:
    """S7.7: dry, high, flat open ground near a road; components >= 1,000 m2; capacity = area x 0.5 / 2."""
    m = (np.nan_to_num(max_depth, nan=1) == 0) & (np.nan_to_num(hand) >= 10) & (np.nan_to_num(slope_deg, nan=90) <= 10) \
        & (np.nan_to_num(dist_road_m, nan=1e9) <= 150)
    lab, n = ndimage.label(m)
    if n == 0:
        return []
    sizes = np.bincount(lab.ravel())[1:]
    centers = ndimage.center_of_mass(m, lab, range(1, n + 1))
    out = []
    for k in np.argsort(-sizes):
        area = float(sizes[k]) * cell * cell
        if area < 1000:
            break
        r, c = centers[k]
        out.append({"row": int(round(r)), "col": int(round(c)), "area_m2": area,
                    "capacity": int(math.floor(area * 0.5 / 2.0)), "label": "temporary open-air assembly point"})
        if len(out) >= top:
            break
    return out


def hazard_pieces(geom, grid, hit_flat: np.ndarray, step_m: float = 30.0, pad_m: float = 30.0,
                  skip: set | None = None) -> list[tuple[float, float]]:
    """Where along an edge the closing hazard actually is: (start, end) fractions of the line's length covering the
    sample points whose cell is hit (bool per flat cell index), padded by `pad_m` and merged. A slide or a flooded dip
    blocks a road at a place, so the map draws these pieces as closed and the rest of a long edge as cut off."""
    L = float(geom.length)
    if L <= 0:
        return []
    d = np.append(np.arange(0, L, step_m), L)
    pts = [geom.interpolate(x) for x in d]
    xs = np.array([p.x for p in pts]); ys = np.array([p.y for p in pts])
    c = np.floor((xs - grid.x0) / grid.cell).astype(int)
    r = np.floor((grid.y0 - ys) / grid.cell).astype(int)
    ok = (r >= 0) & (r < grid.height) & (c >= 0) & (c < grid.width)
    flat = np.where(ok, r * grid.width + c, -1)
    hit = np.array([f >= 0 and bool(hit_flat[f]) and not (skip and int(f) in skip) for f in flat])
    out: list[list[float]] = []
    for i in np.flatnonzero(hit):
        a, b = max(0.0, d[i] - pad_m), min(L, d[i] + pad_m)
        if out and a <= out[-1][1]:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [(round(a / L, 4), round(b / L, 4)) for a, b in out]
