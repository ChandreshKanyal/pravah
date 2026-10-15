"""S8 at run time: closures, adjusted network, demand, supply, assignment, routes, bridges and GeoJSON outputs."""
import json
import math
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import LineString, mapping, shape

from app.config import get_settings
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


def load_network(edges: gpd.GeoDataFrame, nodes: gpd.GeoDataFrame) -> Network:
    edges = edges.reset_index(drop=True)
    edges["cells"] = edges["cells"].apply(lambda c: [int(x) for x in c])
    return Network(edges, edges.to_crs("EPSG:4326"), nodes, cKDTree(nodes[["x", "y"]].to_numpy()), nodes["node"].to_numpy())


def _cell_xy(grid, r, c):
    return grid.x0 + (c + 0.5) * grid.cell, grid.y0 - (r + 0.5) * grid.cell


def plan(area, p: ScenarioParams, depth: np.ndarray, lsi_dyn: np.ndarray | None, stage: np.ndarray,
         exposure_ctx: dict, warnings: list[str]) -> dict:
    net: Network | None = area.networks.get(p.travel_mode)
    if net is None:
        warnings.append(f"No {p.travel_mode} road network for this area; routing skipped")
        return {}
    grid, H = area.grid, depth.shape[0]
    E = net.edges

    # S8.1 closures
    blocked = np.zeros(len(E), bool)
    if p.blocked_polygons:
        polys = [shape(g.get("geometry", g)) for g in p.blocked_polygons]
        blk = gpd.GeoSeries(polys, crs="EPSG:4326")
        blocked = np.array([any(geom.intersects(b) for b in blk) for geom in net.edges_ll.geometry])
    limit = p.walk_depth_limit_m if p.travel_mode == "walk" else p.vehicle_depth_limit_m
    first, reason, edge_lsi = routing.edge_states(E["cells"].tolist(), E["bridge"].to_numpy(), blocked, depth,
                                                  lsi_dyn, stage, area.reach_id_30, limit, p.bridge_cut_stage_m,
                                                  get_settings().lsi_close_share)
    # S8.2 adjusted network at the evaluation hour
    t_eval = min(H, p.evac_start_hour + 1)
    w = routing.edge_weight(E["t0_s"].to_numpy(), edge_lsi[:, t_eval - 1], E["crowd_e"].to_numpy(),
                            E["slope_adjacent"].to_numpy())
    G = routing.build_graph(E["u"].to_numpy(), E["v"].to_numpy(), w, first > t_eval)

    def nearest_node(x, y):
        return net.node_ids[net.tree.query([x, y])[1]]

    # S8.3 demand: exposed buildings + exposed unattributed grid people, snapped to nodes
    demand_f: dict = {}
    rows, cols, pop_b = exposure_ctx["rows"], exposure_ctx["cols"], exposure_ctx["pop_b"]
    cfg = get_settings()
    ex_b = (exposure_ctx["d_b"] >= routing_wet()).any(axis=0) | (exposure_ctx["ls_b"] >= cfg.lsi_demand_class).any(axis=0)
    watch = int(((exposure_ctx["ls_b"] >= 4).any(axis=0) & ~ex_b).sum())
    if watch:
        warnings.append(f"{watch} buildings reach landslide susceptibility class 4 in this scenario: monitor slopes and "
                        "be ready to move people (not counted as evacuation demand)")
    if ex_b.any():
        xs, ys = _cell_xy(grid, rows[ex_b], cols[ex_b])
        _, idx = net.tree.query(np.column_stack([xs, ys]))
        for node, people in zip(net.node_ids[idx], pop_b[ex_b]):
            demand_f[node] = demand_f.get(node, 0.0) + float(people)
    pop_un = exposure_ctx["pop_un"]
    wet_un = (np.nan_to_num(depth).max(axis=0) >= routing_wet())
    if lsi_dyn is not None:
        wet_un |= lsi_dyn.max(axis=0) >= cfg.lsi_demand_class
    rr, cc = np.nonzero(wet_un & (pop_un > 0))
    if len(rr):
        xs, ys = _cell_xy(grid, rr, cc)
        _, idx = net.tree.query(np.column_stack([xs, ys]))
        for node, people in zip(net.node_ids[idx], pop_un[rr, cc]):
            demand_f[node] = demand_f.get(node, 0.0) + float(people)
    demand = {n: int(math.ceil(v)) for n, v in demand_f.items() if v >= 0.5}

    # S8.4 supply: shelters (minus disabled, plus extra) and assembly points
    max_depth = depth.max(axis=0)  # NaN where permanent water
    ap = routing.assembly_points(max_depth, area.hand, area.slope_deg, area.lsi_class, area.dist_road_m, grid.cell)
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
        elif lsi_dyn is not None and lsi_dyn[:, r, c].max() > cfg.lsi_shelter_max_class:
            status[s["id"]] = "landslide_risk"
        elif s["node"] not in G:
            status[s["id"]] = "unreachable"
        else:
            status[s["id"]] = "usable"
            caps[s["id"]], nodes_of[s["id"]] = int(s["capacity"]), s["node"]

    # S8.5-S8.7 travel times, assignment, routes
    times = routing.travel_times(G, nodes_of, p.max_travel_min * 60)
    alloc, gap, _ = routing.transport_solve(demand, caps, times)
    assigned = {sid: 0 for sid in caps}
    routes = []
    import networkx as nx
    for (node, sid), people in alloc.items():
        assigned[sid] += people
        path = nx.shortest_path(G, node, nodes_of[sid], weight="w")
        eidx = [G[a][b]["e"] for a, b in zip(path[:-1], path[1:])]
        fc = int(min((first[e] for e in eidx), default=routing.NEVER))
        until = None if fc >= routing.NEVER else fc
        geom = _path_geom(net, eidx, node)
        routes.append({"from_node": int(node), "to_shelter": sid, "people": int(people),
                       "eta_min": round(times[sid][node] / 60, 1), "passable_until_h": until,
                       "use_now_gone_soon": until is not None and until <= p.evac_start_hour + 2, "geometry": geom})
    routes.sort(key=lambda r: -r["people"])
    if gap > 0:
        spare_ap = [s["id"] for s in supply if s["source"] == "assembly" and status[s["id"]] == "usable"
                    and caps[s["id"]] - assigned.get(s["id"], 0) > 0]
        warnings.append(f"Capacity gap: {gap} people have no reachable shelter in this scenario. "
                        "Consider external transport or additional shelters.")
        if spare_ap:
            warnings.append(f"Assembly points with spare capacity: {', '.join(spare_ap[:5])}")

    # S8.9 bridges (one row per physical bridge, both directions merged)
    bridges, seen = [], {}
    for e in np.flatnonzero(E["bridge"].to_numpy()):
        key = frozenset((E.at[e, "u"], E.at[e, "v"]))
        if key in seen:
            b = bridges[seen[key]]
            if first[e] < (b["first_closed_hour"] or routing.NEVER):
                b["first_closed_hour"], b["reason"] = int(first[e]), reason[e]
            continue
        mid = net.edges_ll.geometry.iloc[e].interpolate(0.5, normalized=True)
        seen[key] = len(bridges)
        bridges.append({"id": f"B{len(bridges) + 1}", "name": E.at[e, "name"] or "Unnamed bridge",
                        "lon": round(mid.x, 6), "lat": round(mid.y, 6),
                        "first_closed_hour": None if first[e] >= routing.NEVER else int(first[e]),
                        "reason": reason[e] or None})
    bridges.sort(key=lambda b: (b["first_closed_hour"] or routing.NEVER, b["id"]))

    shelters_out = []
    for s in supply:
        a = assigned.get(s["id"], 0)
        shelters_out.append({"id": s["id"], "name": s["name"], "kind": s.get("kind", ""), "lon": s["lon"], "lat": s["lat"],
                             "capacity": int(s["capacity"]), "assigned": int(a), "spare": int(max(0, s["capacity"] - a)),
                             "status": status[s["id"]], "note": s.get("note", ""),
                             "capacity_confidence": s.get("capacity_confidence", "low")})

    # S7.8 staging points: dry, flat, near a drive road open all scenario, close to the worst clusters
    staging = _staging(area, p, depth, exposure_ctx.get("clusters", []), first, net)

    roads_fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": mapping(g), "properties": {
            "first_closed_hour": None if first[i] >= routing.NEVER else int(first[i]), "reason": reason[i] or None,
            "bridge": bool(E.at[i, "bridge"]), "name": E.at[i, "name"], "highway": E.at[i, "highway"]}}
        for i, g in enumerate(net.edges_ll.geometry)]}
    routes_fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": r.pop("geometry"), "properties": r} for r in routes]}
    return {"shelters": shelters_out, "bridges": bridges, "capacity_gap_people": int(gap),
            "assembly_points": [{k: v for k, v in s.items() if k in ("id", "name", "lon", "lat", "capacity", "area_m2", "label")}
                                for s in supply if s["source"] == "assembly"],
            "staging_points": staging, "roads_geojson": json.dumps(roads_fc), "routes_geojson": json.dumps(routes_fc),
            "routes_summary": [r["properties"] for r in routes_fc["features"]][:50],
            "people_to_evacuate": int(sum(demand.values()))}


def routing_wet() -> float:
    return 0.05


def _lonlat_rc(grid, lon, lat):
    from app.engines.grid import lonlat_to_rowcol
    r, c = lonlat_to_rowcol(grid, lon, lat)
    return int(np.clip(r, 0, grid.height - 1)), int(np.clip(c, 0, grid.width - 1))


def _path_geom(net: Network, eidx: list[int], start_node) -> dict:
    coords = []
    for e in eidx:
        cs = list(net.edges_ll.geometry.iloc[e].coords)
        coords.extend(cs if not coords else cs[1:])
    if len(coords) < 2:
        n = net.nodes[net.nodes["node"] == start_node].iloc[0]
        coords = [(n["lon"], n["lat"]), (n["lon"], n["lat"])]
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
        out.append({"id": f"P{len(out) + 1}", "lon": round(float(lon), 6), "lat": round(float(lat), 6),
                    "near_cluster": cl.get("id"), "reason": "ambulance/police/medical staging"})
        if len(out) >= top:
            break
    return out
