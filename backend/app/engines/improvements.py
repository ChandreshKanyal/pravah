"""Pre-monsoon improvement list: places where maintenance would most reduce flooding or waterlogging, each with its
evidence. Pure NumPy/SciPy/NetworkX; the imagery fetch, Gemini review and web search live in
app/pipeline/improvements.py.

Honest by construction. 10 m open imagery cannot show a choked drain or a pile of garbage, so drains, culverts and road
low spots are ranked by what a blockage there would cost (water arriving from upstream, people on low ground), and
imagery is only used for what it can see at 10 m: weed mats on open channels, new construction or new bare ground in
the flood path. Every item says which kind of evidence it rests on.
"""
import math

import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

CATS: dict[str, dict] = {
    "reported": {"title": "Reported waterlogging spot", "dept": ("Ward office and storm-water drains", "Tehsil office and PWD")},
    "culvert": {"title": "Desilt the culvert or drain crossing", "dept": ("Municipal storm-water drains", "PWD and Jal Sansthan")},
    "low_spot": {"title": "Clear road inlets at a low spot", "dept": ("Municipal storm-water drains", "PWD")},
    "choked_channel": {"title": "Clear weeds and silt from the channel", "dept": ("Municipal storm-water drains", "Irrigation department")},
    "single_exit": {"title": "Keep the only road out clear", "dept": ("Traffic police and ward office", "Police and PWD")},
    "encroachment": {"title": "Check new construction in the flood path", "dept": ("Building proposals and ward office", "Tehsil office and development authority")},
    "bare_ground": {"title": "Check new bare ground or dumped muck near the stream", "dept": ("Solid waste management", "PWD and forest department")},
}
# order on the list and on ties: things with direct evidence first, then model-ranked maintenance
WEIGHT = {"reported": 1.0, "choked_channel": 0.95, "culvert": 0.9, "low_spot": 0.85, "single_exit": 0.8,
          "encroachment": 0.75, "bare_ground": 0.6}


def dept(cat: str, urban: bool) -> str:
    return CATS[cat]["dept"][0 if urban else 1]


def in_box(lon: float, lat: float, bbox) -> bool:
    w, s, e, n = bbox
    return w <= lon <= e and s <= lat <= n


def dist_m(lon1, lat1, lon2, lat2) -> float:
    k = 111_320.0
    return math.hypot((lon2 - lon1) * k * math.cos(math.radians((lat1 + lat2) / 2)), (lat2 - lat1) * k)


def dedupe(items: list[dict], min_m: float) -> list[dict]:
    """Greedy by score: drop an item within `min_m` of a better one of the same category."""
    out: list[dict] = []
    for it in sorted(items, key=lambda d: -d["score"]):
        if all(o["category"] != it["category"] or dist_m(o["lon"], o["lat"], it["lon"], it["lat"]) >= min_m for o in out):
            out.append(it)
    return out


def disk_sum(a: np.ndarray, radius_m: float, cell: float) -> np.ndarray:
    """Sum of `a` within a disk around every cell."""
    r = max(1, int(round(radius_m / cell)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    k = (xx * xx + yy * yy <= r * r).astype(np.float64)
    return ndi.convolve(np.nan_to_num(a).astype(np.float64), k, mode="constant")


def _item(cat: str, lon: float, lat: float, score: float, why: list[str], action: str, urban: bool, *, place: str = "",
          basis: str, numbers: dict | None = None, confidence: str = "check") -> dict:
    return {"category": cat, "title": CATS[cat]["title"], "place": place, "lon": round(float(lon), 6), "lat": round(float(lat), 6),
            "score": round(float(score), 3), "why": why, "action": action, "department": dept(cat, urban), "basis": basis,
            "numbers": numbers or {}, "confidence": confidence, "images": [], "sources": [], "ai": None}


def _nm(x) -> str:
    if isinstance(x, list):
        x = next((v for v in x if v), "")
    s = "" if x is None else str(x)
    return "" if s in ("<NA>", "nan", "None") else s


# ---------- model-ranked maintenance (works without imagery) ----------
def culverts(cands: list[dict], hand: np.ndarray, upa: np.ndarray, pop: np.ndarray, cell: float, bbox, urban: bool,
             wtype: dict | None = None, top: int = 8) -> list[dict]:
    """OSM culverts and waterway x road crossings, ranked by the water that reaches them and the people a blockage would
    flood: people on low ground (< 2 m above the drainage) within 400 m. Points sampled along channels are not used:
    only places where a road squeezes the flow through an opening. A river crossing is a bridge opening."""
    wtype = wtype or {}
    cands = [c for c in cands if c["type"] in ("culvert", "road crossing") and in_box(c["lon"], c["lat"], bbox)]
    if not cands:
        return []
    low_people = disk_sum(np.where(np.nan_to_num(hand, nan=99) <= 2, pop, 0), 400, cell)
    upa_n = ndi.maximum_filter(np.nan_to_num(upa), size=3)  # snap to the stream cell beside the crossing
    r = np.array([c["row"] for c in cands]); c_ = np.array([c["col"] for c in cands])
    ppl, up = low_people[r, c_], upa_n[r, c_]
    s = 0.5 * np.log1p(up) / (np.log1p(up.max()) or 1) + 0.5 * ppl / (ppl.max() or 1)
    out = []
    for k, cd in enumerate(cands):
        if ppl[k] < 50 and up[k] < 1:
            continue
        ww = wtype.get(str(cd.get("waterway_id")), "")
        if cd["type"] == "culvert":
            kind, what = "culvert", "culvert"
        elif ww in ("river", "canal") or up[k] >= 10:
            kind, what = "bridge opening", f"bridge opening over the {cd.get('name') or ww or 'river'}"
        else:
            kind, what = "drain crossing", f"{ww or 'drain'} crossing under the road"
        why = []
        if up[k] >= 0.1:
            why.append(f"Water from about {up[k]:.1f} km² upstream passes here")
        why.append(f"About {int(round(ppl[k], -1)):,} people live on low ground (under 2 m above the drainage) within 400 m")
        why.append(f"OpenStreetMap: {what}")
        act = ("Clear silt, debris and dumped waste under the bridge opening before heavy rain so the full span carries water."
               if kind == "bridge opening" else
               f"Desilt and clear the {kind} before heavy rain: remove debris at the inlet and check the opening is not narrowed.")
        it = _item("culvert", cd["lon"], cd["lat"], s[k], why, act, urban, place=cd.get("name", ""), basis="model",
                   numbers={"upstream_km2": round(float(up[k]), 2), "people_low_400m": int(ppl[k]), "kind": kind})
        if kind == "bridge opening":
            it["title"] = "Clear silt and debris under the bridge"
        out.append(it)
    out, kept, n_br = dedupe(out, 250), [], 0
    for it in out:  # a big river has many bridges: keep the worst three so smaller drains still make the list
        if it["numbers"]["kind"] == "bridge opening":
            n_br += 1
            if n_br > 3:
                continue
        kept.append(it)
    return kept[:top]


def low_spots(pluvial: dict, dist_road: np.ndarray, pop: np.ndarray, rc2ll, cell: float, bbox, urban: bool, top: int = 6) -> list[dict]:
    """Hollows in the bare-earth terrain that a road runs through: they fill first and stay wet when inlets are blocked.
    `fill_mm` = rain beyond what drains carry that fills the hollow (volume / (runoff C x catchment area))."""
    lab, dep = pluvial["dep_label"], pluvial["dep_depth"]
    road = (np.nan_to_num(dist_road, nan=1e9) <= 15) & (lab > 0) & (dep >= 0.2)
    if not road.any():
        return []
    ppl = disk_sum(pop, 200, cell)
    size = np.bincount(lab.ravel())
    out = []
    for k in np.unique(lab[road]):
        if not 2 <= size[k] <= 300:  # one 30 m cell is terrain noise; hundreds of cells is a basin, not a road dip
            continue
        cells = np.argwhere(road & (lab == k))
        d = dep[cells[:, 0], cells[:, 1]]
        i = int(np.argmax(d))
        r, c = cells[i]
        lon, lat = rc2ll(r, c)
        if not in_box(lon, lat, bbox):
            continue
        v, a, C = pluvial["v_dep"][k], pluvial["ws_area_m2"][k], pluvial["c_ws"][k]
        fill = v / max(C * a, 1.0) * 1000
        depth, p = float(d[i]), float(ppl[r, c])
        if p < 100:
            continue
        s = 0.4 * min(depth, 2) / 2 + 0.4 * min(p, 5000) / 5000 + 0.2 * (1 - min(fill, 100) / 100)
        out.append(_item("low_spot", lon, lat, s, [
            f"A hollow about {depth:.1f} m deep that the road runs through (about {size[k] * cell * cell / 10_000:.1f} ha)",
            ("It fills with the first few mm of rain the drains cannot carry" if fill < 5 else
             f"It fills with about {fill:.0f} mm of rain that the drains do not carry") if fill < 300 else "It fills slowly, but stays wet once full",
            f"About {int(round(p, -1)):,} people live within 200 m",
        ], "Clean the road inlets and the drain at this low spot before heavy rain; keep a pump ready when it rains hard.",
            urban, basis="model", numbers={"depth_m": round(depth, 2), "fill_mm": round(float(fill)), "people_200m": int(p)}))
    return dedupe(out, 250)[:top]


def single_exits(G, hand: np.ndarray, stream: np.ndarray, pop: np.ndarray, ll2rc, rc2ll, bbox, urban: bool,
                 min_people: int = 300, top: int = 6) -> list[dict]:
    """Road links that are the only way out for a neighbourhood (graph bridges) and run on low ground or over a stream:
    a parked truck, a stall or one flooded dip there cuts everyone behind it off. People per side from the population
    grid, each populated cell counted at its nearest road node."""
    import networkx as nx
    U = nx.Graph(G.to_undirected())
    if U.number_of_edges() == 0:
        return []
    nodes = list(U.nodes)
    xy = np.array([[U.nodes[n]["x"], U.nodes[n]["y"]] for n in nodes], float)
    lat0 = float(np.mean(xy[:, 1]))
    sc = np.array([111_320 * math.cos(math.radians(lat0)), 110_540])
    rr, cc = np.nonzero(np.nan_to_num(pop) > 0)
    plon, plat = rc2ll(rr, cc)
    _, near = cKDTree(xy * sc).query(np.c_[plon, plat] * sc)
    w = np.bincount(near, weights=np.nan_to_num(pop)[rr, cc], minlength=len(nodes))
    idx = {n: i for i, n in enumerate(nodes)}
    br = list(nx.bridges(U))
    if not br:
        return []
    H = U.copy()
    H.remove_edges_from(br)
    cid: dict = {}
    comp_w: list[float] = []
    comp_n: list[int] = []
    for k, comp in enumerate(nx.connected_components(H)):
        for n in comp:
            cid[n] = k
        comp_w.append(float(sum(w[idx[n]] for n in comp)))
        comp_n.append(len(comp))
    T = nx.Graph()
    T.add_nodes_from(range(len(comp_w)))
    for u, v in br:
        T.add_edge(cid[u], cid[v])
    sub = np.array(comp_w)
    parent: dict[int, int] = {}
    for tree in nx.connected_components(T):  # root each piece at its biggest component; accumulate subtree people
        root = max(tree, key=lambda k: comp_n[k])
        order = list(nx.bfs_tree(T, root))
        for a, b in nx.bfs_edges(T, root):
            parent[b] = a
        for k in reversed(order):
            if k in parent:
                sub[parent[k]] += sub[k]
    hand_ = np.nan_to_num(hand, nan=99)
    st = ndi.binary_dilation(stream, iterations=1)
    out = []
    for u, v in br:
        a, b = cid[u], cid[v]
        child = b if parent.get(b) == a else a if parent.get(a) == b else None
        if child is None:
            continue
        cut = float(sub[child])
        if cut < min_people:
            continue
        d = U.edges[u, v]
        lon, lat = (U.nodes[u]["x"] + U.nodes[v]["x"]) / 2, (U.nodes[u]["y"] + U.nodes[v]["y"]) / 2
        if not in_box(lon, lat, bbox):
            continue
        r, c = ll2rc(lon, lat)
        if not (0 <= r < hand_.shape[0] and 0 <= c < hand_.shape[1]):
            continue
        low, over = float(hand_[r, c]), bool(st[r, c])
        if low > 3 and not over:
            continue
        name = _nm(d.get("name"))
        why = [f"The only drivable road out for about {int(round(cut, -1)):,} people behind it (OpenStreetMap roads; footpaths not counted)",
               "It crosses a stream or drain" if over else f"It runs on low ground, about {low:.1f} m above the nearest stream"]
        s = min(cut, 5000) / 5000 * 0.7 + (0.3 if over else 0.3 * (3 - low) / 3)
        out.append(_item("single_exit", lon, lat, s, why,
                         "Keep this road clear in heavy rain (no parking or stalls, roadside drain cleaned) and plan a second way out, "
                         "such as a footpath or a temporary crossing.", urban, place=name, basis="model",
                         numbers={"people_cut_off": int(cut), "hand_m": round(low, 1), "crosses_stream": over}))
    return dedupe(out, 300)[:top]


# ---------- imagery (Sentinel-2 / Dynamic World, 10 m) ----------
def _clusters(mask: np.ndarray, min_px: int, value: np.ndarray | None = None):
    """Connected patches of at least `min_px` pixels: yields (pixel count, representative row, col, member pixels)."""
    lab, n = ndi.label(mask, structure=np.ones((3, 3)))
    if n == 0:
        return
    sizes = np.bincount(lab.ravel(), minlength=n + 1)
    for k, sl in enumerate(ndi.find_objects(lab), start=1):
        if sizes[k] < min_px:
            continue
        rr, cc = np.nonzero(lab[sl] == k)
        rr, cc = rr + sl[0].start, cc + sl[1].start
        if value is not None:
            i = int(np.argmax(value[rr, cc]))
        else:  # member pixel nearest the centroid
            i = int(np.argmin((rr - rr.mean()) ** 2 + (cc - cc.mean()) ** 2))
        yield int(sizes[k]), int(rr[i]), int(cc[i]), (rr, cc)


def choked_channels(arr: dict, channel: np.ndarray, names: np.ndarray, rc2ll, window, urban: bool, top: int = 6) -> list[dict]:
    """Stretches of a mapped river or canal whose surface reads as vegetation (NDVI >= 0.35) in recent clear Sentinel-2
    scenes: floating weeds (water hyacinth), reeds or silt islands that slow the flow. Open water reads below about 0.1."""
    ndvi = np.nan_to_num(arr["ndvi"], nan=-1)
    green = channel & (ndvi >= 0.35)
    out = []
    for n, r, c, (rr, cc) in _clusters(green, 3, ndvi):
        lon, lat = rc2ll(r, c)
        name = str(names[r, c]) if names is not None and names[r, c] else ""
        mean = float(ndvi[rr, cc].mean())
        length = n * 10
        out.append(_item("choked_channel", lon, lat, min(length, 300) / 300, [
            f"About {length} m of the {name or 'channel'} looks green from space (vegetation index {mean:.2f}; open water is below 0.1)",
            f"Sentinel-2 images from {window[0]} to {window[1]} ({window[2]} scenes, clouds removed)",
        ], "Inspect and remove floating weeds, reeds and silt here before the next heavy rain; they slow the flow and back water up.",
            urban, place=name, basis="imagery", numbers={"length_m": length, "ndvi": round(mean, 2)}))
    return dedupe(out, 300)[:top]


def new_construction(arr: dict, hand: np.ndarray, ds: np.ndarray, rc2ll, urban: bool, top: int = 5) -> list[dict]:
    """Land that turned built-up (Dynamic World built probability >= 0.45 now, <= 0.2 in 2016-17) on former water or
    wetland, or on low ground beside a stream (< 2 m above it, within 150 m)."""
    wet = (np.nan_to_num(arr["wet_then"]) >= 0.4) | (np.nan_to_num(arr["water_occ"]) >= 25)
    floodway = (np.nan_to_num(hand, nan=99) <= 2) & (np.nan_to_num(ds, nan=1e9) <= 150)
    nb = (np.nan_to_num(arr["built_now"]) >= 0.45) & (np.nan_to_num(arr["built_then"], nan=1) <= 0.2) & (wet | floodway)
    out = []
    for n, r, c, (rr, cc) in _clusters(nb, 15):
        lon, lat = rc2ll(r, c)
        on_wet = float(wet[rr, cc].mean()) >= 0.5
        area = n * 100
        out.append(_item("encroachment", lon, lat, min(area, 20_000) / 20_000 + (0.2 if on_wet else 0), [
            f"About {area:,} m² became built-up between 2016–17 and the last 12 months (Google Dynamic World land cover)",
            "It was water or wetland in 2016–17" if on_wet else "It is on low ground beside a stream (under 2 m above it)",
        ], "Check whether this construction narrows the channel or blocks the flow path, and whether its drainage was approved.",
            urban, basis="imagery", numbers={"area_m2": area, "former_wetland": on_wet}))
    return dedupe(out, 300)[:top]


def new_bare(arr: dict, hand: np.ndarray, ds: np.ndarray, rc2ll, urban: bool, top: int = 4) -> list[dict]:
    """New bare ground near a stream (Dynamic World bare >= 0.4 now, <= 0.15 in 2016-17; < 10 m above and within 200 m
    of the stream): construction muck, a landslide scar or a shifted river bar. Loose material washes into channels."""
    near = (np.nan_to_num(hand, nan=99) <= 10) & (np.nan_to_num(ds, nan=1e9) <= 200)
    nb = (np.nan_to_num(arr["bare_now"]) >= 0.4) & (np.nan_to_num(arr["bare_then"], nan=1) <= 0.15) & near
    out = []
    for n, r, c, _ in _clusters(nb, 15):
        lon, lat = rc2ll(r, c)
        area = n * 100
        out.append(_item("bare_ground", lon, lat, min(area, 20_000) / 20_000, [
            f"About {area:,} m² of new bare ground within 200 m of the stream since 2016–17 (Google Dynamic World)",
            "It could be dumped construction muck, a landslide scar or a shifted river bar; loose material washes into the channel in heavy rain",
        ], "Check whether debris or muck is dumped here; it must not be left where rain can wash it into the channel.",
            urban, basis="imagery", numbers={"area_m2": area}))
    return dedupe(out, 300)[:top]


def rank(items: list[dict], cap: int = 30) -> list[dict]:
    """One list, best first: category weight x score; ids I1, I2..."""
    for it in items:
        it["rank_score"] = round(WEIGHT[it["category"]] * (0.5 + 0.5 * min(1.0, it["score"])), 3)
    items = sorted(items, key=lambda d: -d["rank_score"])[:cap]
    for i, it in enumerate(items, start=1):
        it["id"] = f"I{i}"
    return items
