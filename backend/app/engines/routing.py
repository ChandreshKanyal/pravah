"""Evacuation routing with capacity-aware assignment (S8). Pure NetworkX/SciPy/NumPy, no I/O."""
import itertools
import math

import networkx as nx
import numpy as np
import shapely
from scipy import ndimage
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

NEVER = 10**6  # first_closed_hour sentinel
OVERFLOW_COST = 10_000_000
WALK_FLAT_KMH = 6 * math.exp(-3.5 * 0.05)  # Tobler on flat ground, 5.04 km/h


def cells_csr(cells: list) -> tuple[np.ndarray, np.ndarray]:
    """Every edge's sample cells in one flat array plus each edge's start offset (CSR), for per-edge reductions."""
    lens = np.fromiter((len(c) for c in cells), np.int64, len(cells))
    starts = np.zeros(len(cells) + 1, np.int64)
    np.cumsum(lens, out=starts[1:])
    flat = np.fromiter(itertools.chain.from_iterable(cells), np.int64, int(starts[-1]))
    return flat, starts


def edge_states(cells: list[list[int]], blocked: np.ndarray, depth: np.ndarray, depth_limit_m: float,
                bridge_first: np.ndarray | None = None, bridge_cells: list[set] | None = None,
                csr: tuple[np.ndarray, np.ndarray] | None = None) -> tuple[np.ndarray, list[str]]:
    """first_closed_hour (1-based, NEVER if open) and reason per edge.

    Bridges (engines/bridges.py) close only when OSM marks them under construction/closed or the river reaches their
    deck; `bridge_first[e]` is the first such hour for the spans edge e runs over (NEVER if none). The cells over a span
    (`bridge_cells[e]`) are left out of the flood test: they lie above the water. A bridge closing and a flood in the
    same hour count as the bridge. `csr` (from cells_csr) may be passed to skip flattening the cells.

    Vectorized (18 Oct; was a Python loop per edge, 0.4-1.5 s per run): each cell's first flooded hour, then the
    earliest over each edge's cells.
    """
    H = depth.shape[0]
    E = len(cells)
    flat, starts = csr if csr is not None else cells_csr(cells)
    lens = np.diff(starts)
    exceed = np.nan_to_num(depth.reshape(H, -1)) > depth_limit_m  # NaN = permanent river, not flood
    cell_first = np.where(exceed.any(axis=0), exceed.argmax(axis=0) + 1, NEVER).astype(np.int64)
    vals = cell_first[flat]
    if bridge_cells is not None:
        for e in (i for i, b in enumerate(bridge_cells) if b):
            seg = vals[starts[e]:starts[e + 1]]  # a view: the cells over the span never flood the road
            seg[np.fromiter((int(x) in bridge_cells[e] for x in flat[starts[e]:starts[e + 1]]), bool, int(lens[e]))] = NEVER
    flood_first = np.full(E, NEVER, np.int64)
    has = lens > 0
    if vals.size:
        flood_first[has] = np.minimum.reduceat(vals, starts[:-1][has])
    bf = np.full(E, NEVER, np.int64) if bridge_first is None else np.asarray(bridge_first, np.int64)
    first = np.minimum(bf, flood_first)
    reason = np.full(E, "", object)
    reason[(bf <= flood_first) & (bf < NEVER)] = "bridge"
    reason[flood_first < bf] = "flood"
    first[~has], reason[~has] = NEVER, ""  # no cells inside the grid: never closed (except by a drawn block)
    blk = np.asarray(blocked, bool)
    first[blk], reason[blk] = 1, "blocked"
    return first, reason.tolist()


class RouteGraph:
    """The open road network as a sparse matrix for SciPy's Dijkstra (C): travel times from every shelter in a few
    calls and each route from the shelter's shortest-path tree. Replaces a NetworkX search per shelter and per route
    (18 Oct: 199 shelters took 2.8 s of a 7 s routing step). Same graph as build_graph: open edges only, the cheapest of
    parallel edges (the first row on equal weights)."""

    def __init__(self, u, v, w, open_mask):
        rows = np.flatnonzero(open_mask)
        u, v, w = np.asarray(u)[rows], np.asarray(v)[rows], np.asarray(w, np.float64)[rows]
        self.nodes, inv = np.unique(np.concatenate([u, v]), return_inverse=True)
        a, b = inv[:len(rows)], inv[len(rows):]
        order = np.lexsort((rows, w, b, a))
        a, b, w, rows = a[order], b[order], w[order], rows[order]
        keep = np.ones(len(a), bool)
        keep[1:] = (a[1:] != a[:-1]) | (b[1:] != b[:-1])
        self.a, self.b, self.w, self.rows = a[keep], b[keep], w[keep], rows[keep]
        n = len(self.nodes)
        # reversed (b -> a): a search from a shelter gives the time from every node TO the shelter
        self.R = csr_matrix((self.w, (self.b, self.a)), shape=(n, n))
        self._edge: dict | None = None

    def index(self, nodes) -> np.ndarray:
        """Position of each node id in the graph, -1 for nodes no open edge touches."""
        q = np.asarray(list(nodes), dtype=self.nodes.dtype) if not isinstance(nodes, np.ndarray) else nodes
        if not len(self.nodes) or not len(q):
            return np.full(len(q), -1, np.int64)
        i = np.minimum(np.searchsorted(self.nodes, q), len(self.nodes) - 1)
        return np.where(self.nodes[i] == q, i, -1)

    def __contains__(self, node) -> bool:
        return node is not None and bool(self.index([node])[0] >= 0)

    def travel_times(self, shelter_nodes: dict[str, int], cutoff_s: float, targets) -> dict[str, dict]:
        """{shelter_id: {node: seconds to reach the shelter}} for the `targets` nodes within `cutoff_s` (what the
        assignment reads; travel_times below returns every node)."""
        tgt = np.asarray(list(targets))
        ti = self.index(tgt) if len(tgt) else np.zeros(0, np.int64)
        ok = ti >= 0
        tgt, ti = tgt[ok], ti[ok]
        out: dict[str, dict] = {sid: {} for sid in shelter_nodes}
        sids = [sid for sid, nd in shelter_nodes.items() if nd in self]
        for k in range(0, len(sids), 64):  # 64 shelters per call keeps the distance matrix small
            chunk = sids[k:k + 64]
            D = dijkstra(self.R, directed=True, indices=self.index([shelter_nodes[s] for s in chunk]), limit=cutoff_s)
            for row, sid in zip(D[:, ti], chunk):
                hit = np.flatnonzero(row <= cutoff_s)
                out[sid] = {tgt[j].item(): float(row[j]) for j in hit}
        return out

    def paths_to(self, shelter_node, from_nodes, cutoff_s: float | None = None) -> dict:
        """{node: [edge rows along its shortest path to the shelter]} for nodes that reach it."""
        if self._edge is None:
            self._edge = {(int(x), int(y)): int(r) for x, y, r in zip(self.a, self.b, self.rows)}
        s = int(self.index([shelter_node])[0])
        out: dict = {}
        if s < 0:
            return out
        todo = list(from_nodes)
        for lim in ((cutoff_s * (1 + 1e-9) + 1e-6) if cutoff_s is not None else np.inf, np.inf):
            _, pred = dijkstra(self.R, directed=True, indices=s, limit=lim, return_predecessors=True)
            for node, x in zip(todo, self.index(todo)):
                x, path = int(x), []
                while x >= 0 and x != s:
                    p = int(pred[x])
                    if p < 0:  # not reached within this search
                        break
                    path.append(self._edge[(x, p)])  # in the road graph the step runs x -> p
                    x = p
                if x == s:
                    out[node] = path
            todo = [n for n in todo if n not in out]
            if not todo or lim == np.inf:
                break
        return out


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
    keys: dict[str, object] = {}
    for k in demand:  # original node keys (ints stay ints) from their string form, first match wins as in demand_key
        keys.setdefault(str(k), k)
    for d, outs in flow.items():
        if not d.startswith("D:"):
            continue
        node = keys.get(d[2:], d[2:])
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
    xy = shapely.get_coordinates(shapely.line_interpolate_point(geom, d))
    c = np.floor((xy[:, 0] - grid.x0) / grid.cell).astype(int)
    r = np.floor((grid.y0 - xy[:, 1]) / grid.cell).astype(int)
    ok = (r >= 0) & (r < grid.height) & (c >= 0) & (c < grid.width)
    flat = np.where(ok, r * grid.width + c, -1)
    hit = ok & np.asarray(hit_flat)[np.maximum(flat, 0)]
    if skip:
        hit &= np.fromiter((int(f) not in skip for f in flat), bool, len(flat))
    out: list[list[float]] = []
    for i in np.flatnonzero(hit):
        a, b = max(0.0, d[i] - pad_m), min(L, d[i] + pad_m)
        if out and a <= out[-1][1]:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [(round(a / L, 4), round(b / L, 4)) for a, b in out]
