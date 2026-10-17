"""S8 at run time: closures, adjusted network, demand, supply, assignment, routes, bridges and GeoJSON outputs."""
import json
import math
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import shapely
from scipy.spatial import cKDTree
from shapely.geometry import LineString, mapping, shape

from app.engines import bridges as brg
from app.engines import routing
from app.engines.grid import rowcol_to_lonlat
from app.engines.shelters import capacity
from app.models.scenario import ScenarioParams


@dataclass
class Network:
    edges: gpd.GeoDataFrame  # grid CRS
    edges_ll: gpd.GeoDataFrame  # WGS84 geometry, same order
    nodes: gpd.GeoDataFrame
    tree: cKDTree
    node_ids: np.ndarray
    csr: tuple | None = None  # (flat cells, starts) of edges["cells"] (routing.cells_csr)
    static: dict | None = None  # per-edge values that never change between runs (see _static)


def load_network(edges: gpd.GeoDataFrame, nodes: gpd.GeoDataFrame) -> Network:
    edges = edges.reset_index(drop=True)
    edges["cells"] = edges["cells"].apply(lambda c: [int(x) for x in c])
    return Network(edges, edges.to_crs("EPSG:4326"), nodes, cKDTree(nodes[["x", "y"]].to_numpy()), nodes["node"].to_numpy(),
                   csr=routing.cells_csr(edges["cells"].tolist()))


def _static(net: Network) -> dict:
    """Per-edge columns as plain lists, WGS84 geometry and its GeoJSON, and node positions, built once per network
    (the network is cached with the area): reading them row by row from the GeoDataFrame took ~3 s per run."""
    if net.static is None:
        E, ll = net.edges, net.edges_ll.geometry.values
        net.static = {
            "geoms_ll": list(ll),
            "geojson": [mapping(g) for g in shapely.set_precision(ll, 1e-6)],
            "bridge": [bool(x) for x in E["bridge"]], "name": E["name"].tolist(), "highway": E["highway"].tolist(),
            "length_m": E["length_m"].tolist(), "length_r": [round(float(x), 1) for x in E["length_m"]],
            "node_ll": dict(zip(net.nodes["node"].tolist(), zip(net.nodes["lon"].tolist(), net.nodes["lat"].tolist()))),
        }
    return net.static


def _cell_xy(grid, r, c):
    return grid.x0 + (c + 0.5) * grid.cell, grid.y0 - (r + 0.5) * grid.cell


def plan(area, p: ScenarioParams, depth: np.ndarray, stage: np.ndarray,
         exposure_ctx: dict, warnings: list[str]) -> dict:
    net: Network | None = area.networks.get(p.travel_mode)
    if net is None:
        warnings.append(f"No {p.travel_mode} road network for this area; routing skipped")
        return {}
    grid, H = area.grid, depth.shape[0]
    E = net.edges
    S = _static(net)

    # S8.1 closures
    blocked = np.zeros(len(E), bool)
    if p.blocked_polygons:
        polys = [shape(g.get("geometry", g)) for g in p.blocked_polygons]
        blocked[shapely.STRtree(S["geoms_ll"]).query(polys, predicate="intersects")[1]] = True
    limit = p.walk_depth_limit_m if p.travel_mode == "walk" else p.vehicle_depth_limit_m
    # bridges: real OSM spans; closed by OSM status (construction etc.) or when the river reaches the deck
    spans = (area.bridges or {}).get("spans", [])
    links = (area.bridges or {}).get("links", {}).get(p.travel_mode, {})
    if area.bridges is None:
        warnings.append("Bridge spans are not prepared for this area; bridges are treated as roads (re-prepare the area)")
    s_first, s_reason, s_over = brg.closure_hours(spans, stage, p.bridge_margin_m)
    bridge_first = np.full(len(E), routing.NEVER, np.int64)
    bridge_cells: list[set] = [set() for _ in range(len(E))]
    for e_key, ks in links.items():
        e = int(e_key)
        if e < len(E):
            bridge_first[e] = min(int(s_first[k]) for k in ks)
            bridge_cells[e] = set().union(*(spans[k]["cells"] for k in ks))
    first, reason = routing.edge_states(E["cells"], blocked, depth, limit, bridge_first, bridge_cells,
                                        csr=net.csr or routing.cells_csr(E["cells"].tolist()))
    # S8.2 adjusted network at the evaluation hour
    t_eval = min(H, p.evac_start_hour + 1)
    w = routing.edge_weight(E["t0_s"].to_numpy(), E["crowd_e"].to_numpy(), E["slope_adjacent"].to_numpy())
    G = routing.RouteGraph(E["u"].to_numpy(), E["v"].to_numpy(), w, first > t_eval)

    def nearest_node(x, y):
        return net.node_ids[net.tree.query([x, y])[1]]

    # S8.3 demand: exposed buildings + exposed unattributed grid people, snapped to nodes
    demand_f: dict = {}
    access_pm: dict = {}  # people x metres from the home cell to the snapped node (access walk)
    rows, cols, pop_b = exposure_ctx["rows"], exposure_ctx["cols"], exposure_ctx["pop_b"]
    # people move where the flood hazard rating reaches "danger for some" (DEFRA FD2321): moving river water vs
    # standing street water, one rule for every area
    ed = exposure_ctx.get("evac_depth")  # (ordinary, fragile) depth grids from engines/profile.evac_depths
    if ed is not None:
        thr_b = np.where(exposure_ctx["frag"] >= 0.75, ed[1][rows, cols], ed[0][rows, cols])
        thr_un = ed[1]  # unknown structure: assume fragile
    else:
        thr_b, thr_un = routing_wet(), routing_wet()
    ex_b = (exposure_ctx["d_b"] >= thr_b).any(axis=0)
    if ex_b.any():
        xs, ys = _cell_xy(grid, rows[ex_b], cols[ex_b])
        dist, idx = net.tree.query(np.column_stack([xs, ys]))
        for node, people, dm in zip(net.node_ids[idx], pop_b[ex_b], dist):
            demand_f[node] = demand_f.get(node, 0.0) + float(people)
            access_pm[node] = access_pm.get(node, 0.0) + float(people) * float(dm)
    pop_un = exposure_ctx["pop_un"]
    wet_un = (np.nan_to_num(depth).max(axis=0) >= thr_un)
    rr, cc = np.nonzero(wet_un & (pop_un > 0))
    if len(rr):
        xs, ys = _cell_xy(grid, rr, cc)
        dist, idx = net.tree.query(np.column_stack([xs, ys]))
        for node, people, dm in zip(net.node_ids[idx], pop_un[rr, cc], dist):
            demand_f[node] = demand_f.get(node, 0.0) + float(people)
            access_pm[node] = access_pm.get(node, 0.0) + float(people) * float(dm)
    demand = {n: int(math.ceil(v)) for n, v in demand_f.items() if v >= 0.5}
    why = _demand_breakdown(exposure_ctx, depth, thr_b, thr_un)
    # mean access walk per node (straight line x 1.3 detour factor, flat Tobler speed)
    access_s = {n: 1.3 * access_pm.get(n, 0.0) / max(demand_f[n], 1e-9) / (routing.WALK_FLAT_KMH / 3.6) for n in demand}
    # actual travel time per edge: free-flow time slowed by crowding; the slope factor in `w` is risk aversion for
    # choosing routes, not time, so ETAs leave it out
    tt = E["t0_s"].to_numpy() * (1 + 0.3 * E["crowd_e"].to_numpy())

    # S8.4 supply: shelters (minus disabled, plus extra) and assembly points
    max_depth = depth.max(axis=0)  # NaN where permanent water
    ap = routing.assembly_points(max_depth, area.hand, area.slope_deg, area.dist_road_m, grid.cell)
    supply = []
    for s in area.shelters:
        supply.append({**s, "capacity": capacity(s["area_m2"], s["floors"], p.sqm_per_person),
                       "node": s.get(f"node_{p.travel_mode}"), "source": "shelter"})
    for i, s in enumerate(p.extra_shelters, start=1):
        r, c = _lonlat_rc(grid, s["lng"], s["lat"])
        x, y = _cell_xy(grid, r, c)
        supply.append({"id": s.get("id") or f"U{i}", "name": s.get("name") or f"User shelter {i}", "kind": "user_added",
                       "lon": s["lng"], "lat": s["lat"], "row": r, "col": c, "capacity": int(s.get("capacity", 0)),
                       "node": nearest_node(x, y), "source": "user", "note": "added by user", "capacity_confidence": "user"})
    for i, a in enumerate(ap, start=1):
        x, y = _cell_xy(grid, a["row"], a["col"])
        lon, lat = rowcol_to_lonlat(grid, a["row"], a["col"])
        a.update(id=f"A{i}", name=f"Assembly point A{i}", kind="assembly_point", lon=round(float(lon), 6),
                 lat=round(float(lat), 6), node=nearest_node(x, y), source="assembly", note=a["label"])
        supply.append(a)
    disabled = set(p.disabled_shelter_ids)
    caps, nodes_of, status = {}, {}, {}
    for s in supply:
        r, c = s["row"], s["col"]
        d_here = depth[:, r, c]
        if s["id"] in disabled:
            status[s["id"]] = "disabled"
        elif np.isnan(d_here).any() or np.nanmax(d_here) > 0:
            status[s["id"]] = "flooded"
        elif s["node"] not in G:
            status[s["id"]] = "unreachable"
        else:
            status[s["id"]] = "usable"
            caps[s["id"]], nodes_of[s["id"]] = int(s["capacity"]), s["node"]

    # S8.5-S8.7 travel times, assignment, routes
    cutoff = p.max_travel_min * 60
    times = G.travel_times(nodes_of, cutoff, demand.keys())
    alloc, gap, _ = routing.transport_solve(demand, caps, times)
    total = int(sum(demand.values()))
    ratio = total / why["central"] if why["central"] > 0 else 0.0
    lo, hi = int(round(why["low"] * ratio)), int(round(why["high"] * ratio))
    placed = total - int(gap) if gap > 0 else sum(caps.values())  # reachable capacity (lower bound when gap > 0)
    assigned = {sid: 0 for sid in caps}
    routes = []
    by_shelter: dict[str, list] = {}
    for node, sid in alloc:
        by_shelter.setdefault(sid, []).append(node)
    paths = {sid: G.paths_to(nodes_of[sid], nodes, cutoff) for sid, nodes in by_shelter.items()}  # one search per shelter
    for (node, sid), people in alloc.items():
        assigned[sid] += people
        eidx = paths[sid][node]
        fc = int(min((first[e] for e in eidx), default=routing.NEVER))
        until = None if fc >= routing.NEVER else fc
        geom = _path_geom(net, eidx, node)
        travel_s = float(sum(tt[e] for e in eidx))
        lon_, lat_ = S["node_ll"][node]
        routes.append({"from_node": int(node), "from_lon": round(float(lon_), 6),
                       "from_lat": round(float(lat_), 6), "to_shelter": sid, "people": int(people),
                       "eta_min": round((travel_s + access_s.get(node, 0.0)) / 60, 1),
                       "access_min": round(access_s.get(node, 0.0) / 60, 1),
                       "length_km": round(float(sum(S["length_m"][e] for e in eidx)) / 1000, 2),
                       "passable_until_h": until,
                       "use_now_gone_soon": until is not None and until <= p.evac_start_hour + 2, "geometry": geom})
    routes.sort(key=lambda r: -r["people"])
    if gap > 0:
        spare_ap = [s["id"] for s in supply if s["source"] == "assembly" and status[s["id"]] == "usable"
                    and caps[s["id"]] - assigned.get(s["id"], 0) > 0]
        warnings.append(f"Capacity gap: {gap} people have no reachable shelter in this scenario. "
                        "Consider external transport or additional shelters.")
        if spare_ap:
            warnings.append(f"Assembly points with spare capacity: {', '.join(spare_ap[:5])}")

    # S8.9 bridges: one row per physical span that crosses a modelled river or that OSM marks as not open
    bridges = []
    for k, sp in enumerate(spans):
        if sp["reach"] < 0 and sp["status"] == "open":
            continue
        bridges.append({"id": "", "name": sp["name"] or "Unnamed bridge", "lon": sp["lon"], "lat": sp["lat"],
                        "first_closed_hour": None if s_first[k] >= routing.NEVER else int(s_first[k]),
                        "reason": s_reason[k] or None, "status": sp["status"], "deck_m": sp["deck_m"],
                        "deck_source": sp.get("deck_source", "terrain"), "length_m": sp["length_m"], "osmid": sp["osmid"],
                        "peak_vs_deck_m": None if not np.isfinite(s_over[k]) else round(float(s_over[k]), 1)})
    bridges.sort(key=lambda b: (b["first_closed_hour"] or routing.NEVER, -(b["peak_vs_deck_m"] if b["peak_vs_deck_m"] is not None else -99)))
    for i, b in enumerate(bridges, start=1):  # B1 = first to close, then the ones the river gets closest to
        b["id"] = f"B{i}"

    shelters_out = []
    for s in supply:
        a = assigned.get(s["id"], 0)
        shelters_out.append({"id": s["id"], "name": s["name"], "kind": s.get("kind", ""), "lon": s["lon"], "lat": s["lat"],
                             "capacity": int(s["capacity"]), "assigned": int(a), "spare": int(max(0, s["capacity"] - a)),
                             "status": status[s["id"]], "note": s.get("note", ""),
                             "capacity_confidence": s.get("capacity_confidence", "low")})

    # S7.8 staging points: dry, flat, near a drive road open all scenario, close to the worst clusters
    staging = _staging(area, p, depth, exposure_ctx.get("clusters", []), first, net)

    # where on each closed edge the hazard is (the rest of a long edge is only cut off): pieces as length fractions,
    # from every hour the cause holds (roads do not reopen in a scenario)
    pieces: dict[int, list] = {}
    flood_any = (np.nan_to_num(depth) > limit).any(axis=0).ravel()
    geoms = E.geometry.values
    for i in np.flatnonzero(first < routing.NEVER):
        if reason[i] == "flood":
            pieces[int(i)] = routing.hazard_pieces(geoms[i], grid, flood_any, skip=bridge_cells[i] or None)
    roads_fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": S["geojson"][i], "properties": {
            "first_closed_hour": None if first[i] >= routing.NEVER else int(first[i]), "reason": reason[i] or None,
            "bridge": S["bridge"][i], "name": S["name"][i], "highway": S["highway"][i], "length_m": S["length_r"][i],
            # flat [a0, b0, a1, b1, ...]: Firestore stores no nested arrays
            **({"hazard": [f for ab in pieces[i] for f in ab]} if pieces.get(i) else {})}}
        for i in range(len(E))]}
    routes_fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": r.pop("geometry"), "properties": r} for r in routes]}
    return {"shelters": shelters_out, "bridges": bridges, "capacity_gap_people": int(gap),
            "assembly_points": [{k: v for k, v in s.items() if k in ("id", "name", "lon", "lat", "capacity", "area_m2", "label")}
                                for s in supply if s["source"] == "assembly"],
            "staging_points": staging, "roads_geojson": json.dumps(roads_fc, separators=(",", ":")), "routes_geojson": json.dumps(routes_fc, separators=(",", ":")),
            "routes_summary": [r["properties"] for r in routes_fc["features"]][:50],
            "people_to_evacuate": total,
            "demand_breakdown": {"flood": int(round(why["flood"] * ratio))},
            "demand_range": [min(lo, total), max(hi, total)],
            "gap_range": [max(0, lo - placed), max(0, hi - placed)]}


# Sensitivity for the decision brief: HAND/rational depths are uncalibrated (errors of tens of percent are normal) and
# gridded population is uncertain at village scale, so the range re-counts demand with depth x0.7 / x1.3 and people
# x0.8 / x1.2. It is a what-if band, not a statistical confidence interval.
DEPTH_SENS, POP_SENS = 0.3, 0.2


def _demand_breakdown(ctx: dict, depth: np.ndarray, thr_b, thr_un) -> dict:
    pop_b, pop_un = ctx["pop_b"], ctx["pop_un"]
    d_b = np.nan_to_num(ctx["d_b"]).max(axis=0)
    d_un = np.nan_to_num(depth).max(axis=0)

    def count(scale: float) -> float:
        return float(pop_b[d_b * scale >= thr_b].sum() + pop_un[d_un * scale >= thr_un].sum())

    central = count(1.0)
    return {"central": central, "flood": central,
            "low": count(1 - DEPTH_SENS) * (1 - POP_SENS), "high": count(1 + DEPTH_SENS) * (1 + POP_SENS)}


def routing_wet() -> float:
    return 0.05


def _lonlat_rc(grid, lon, lat):
    from app.engines.grid import lonlat_to_rowcol
    r, c = lonlat_to_rowcol(grid, lon, lat)
    return int(np.clip(r, 0, grid.height - 1)), int(np.clip(c, 0, grid.width - 1))


def _path_geom(net: Network, eidx: list[int], start_node) -> dict:
    S = _static(net)
    coords = []
    for e in eidx:
        cs = list(S["geoms_ll"][e].coords)
        coords.extend(cs if not coords else cs[1:])
    if len(coords) < 2:
        lon, lat = S["node_ll"][start_node]
        coords = [(lon, lat), (lon, lat)]
    return mapping(LineString(coords))


def _staging(area, p, depth, clusters, first, net: Network, top: int = 5) -> list[dict]:
    drive: Network | None = area.networks.get("drive")
    if drive is None or not clusters:
        return []
    grid = area.grid
    if drive is net:
        open_all = first >= routing.NEVER
    else:  # drive edges never flooded beyond the vehicle limit (cheap re-check on max depth)
        md = np.nan_to_num(depth.max(axis=0)).ravel()
        open_all = np.array([md[c].max(initial=0) <= p.vehicle_depth_limit_m for c in drive.edges["cells"]])
    cells = set()
    for c in drive.edges.loc[open_all, "cells"]:
        cells.update(c)
    if not cells:
        return []
    near_road = np.zeros(grid.height * grid.width, bool)
    near_road[list(cells)] = True
    from scipy.ndimage import binary_dilation
    near_road = binary_dilation(near_road.reshape(grid.height, grid.width), iterations=3)  # ~100 m
    ok = near_road & (np.nan_to_num(depth.max(axis=0), nan=1) == 0) & (np.nan_to_num(area.slope_deg, nan=90) <= 8)
    rr, cc = np.nonzero(ok)
    if not len(rr):
        return []
    pts = np.column_stack([rr, cc])
    tree = cKDTree(pts)
    out, used = [], set()
    for cl in clusters[: top * 2]:
        from app.engines.grid import lonlat_to_rowcol
        r, c = lonlat_to_rowcol(grid, cl["centroid"][0], cl["centroid"][1])
        _, i = tree.query([int(r), int(c)])
        if i in used:
            continue
        used.add(i)
        lon, lat = rowcol_to_lonlat(grid, pts[i][0], pts[i][1])
        out.append({"id": f"G{len(out) + 1}", "lon": round(float(lon), 6), "lat": round(float(lat), 6),
                    "near_cluster": cl.get("id"), "reason": "ambulance/police/medical staging"})
        if len(out) >= top:
            break
    return out
