"""Evacuation routing with capacity-aware assignment (S8). Pure NetworkX/NumPy, no I/O."""
import math

import networkx as nx
import numpy as np
from scipy import ndimage

NEVER = 10**6  # first_closed_hour sentinel
OVERFLOW_COST = 10_000_000
WALK_FLAT_KMH = 6 * math.exp(-3.5 * 0.05)  # Tobler on flat ground, 5.04 km/h


def edge_states(cells: list[list[int]], bridge: np.ndarray, blocked: np.ndarray, depth: np.ndarray,
                lsi_dyn: np.ndarray | None, stage: np.ndarray, reach_id_30: np.ndarray,
                depth_limit_m: float, bridge_cut_stage_m: float,
                lsi_close_share: float = 0.2) -> tuple[np.ndarray, list[str], np.ndarray]:
    """first_closed_hour (1-based, NEVER if open), reason, and edge_lsi[e, t] (max LSI class along edge).

    NOTE(spec-drift, human decision 16 Oct "soften + scope"):
    - landslide closes an edge only when >= lsi_close_share of its sample cells are class 5 (spec: any cell);
      roads score high LSI by construction (distance-to-road factor) and OSM edges here are long;
    - a bridge's interior cells lie over the river, so bridges close on reach stage >= cut or when an approach
      (first/last cell) exceeds the depth limit (spec: any depth > 0 along the bridge).
    """
    H = depth.shape[0]
    d_flat = depth.reshape(H, -1)
    l_flat = lsi_dyn.reshape(H, -1) if lsi_dyn is not None else None
    rid_flat = reach_id_30.ravel()
    E = len(cells)
    first = np.full(E, NEVER, np.int64)
    reason = [""] * E
    edge_lsi = np.zeros((E, H), np.uint8)
    for e, c in enumerate(cells):
        if blocked[e]:
            first[e], reason[e] = 1, "blocked"
            continue
        if not c:
            continue
        dc = np.nan_to_num(d_flat[:, c])  # NaN = permanent river, not flood
        slide5 = np.zeros(H, bool)
        if l_flat is not None:
            lc = l_flat[:, c]
            edge_lsi[e] = lc.max(axis=1)
            slide5 = (lc == 5).mean(axis=1) >= lsi_close_share
        if bridge[e]:
            approach = dc[:, [0, -1]].max(axis=1)
            rids = np.unique(rid_flat[c])
            rids = rids[rids >= 0]
            st = stage[rids].max(axis=0) if len(rids) else np.zeros(H)
            causes = [("bridge", (st >= bridge_cut_stage_m) | (approach > depth_limit_m)), ("landslide", slide5)]
        else:
            causes = [("flood", dc.max(axis=1) > depth_limit_m), ("landslide", slide5)]
        for t in range(H):
            hit = [name for name, m in causes if m[t]]
            if hit:
                first[e], reason[e] = t + 1, hit[0]
                break
    return first, reason, edge_lsi


def edge_weight(t0_s, edge_lsi_eval, crowd_e, slope_adjacent) -> np.ndarray:
    """w = t0 x landslide factor x (1 + 0.3 crowd) x (1.2 if steep slope beside the road)."""
    lsi = np.asarray(edge_lsi_eval)
    f_lsi = np.where(lsi == 4, 1.5, np.where(lsi == 3, 1.2, 1.0))
    return np.asarray(t0_s) * f_lsi * (1 + 0.3 * np.asarray(crowd_e)) * np.where(np.asarray(slope_adjacent), 1.2, 1.0)


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


def assembly_points(max_depth: np.ndarray, hand: np.ndarray, slope_deg: np.ndarray, lsi_class: np.ndarray | None,
                    dist_road_m: np.ndarray, cell: float, top: int = 10) -> list[dict]:
    """S7.7: dry, high, flat, stable open ground near a road; components >= 1,000 m2; capacity = area x 0.5 / 2."""
    m = (np.nan_to_num(max_depth, nan=1) == 0) & (np.nan_to_num(hand) >= 10) & (np.nan_to_num(slope_deg, nan=90) <= 10) \
        & (np.nan_to_num(dist_road_m, nan=1e9) <= 150)
    if lsi_class is not None:
        m &= lsi_class <= 2
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
