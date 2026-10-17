"""OpenStreetMap via OSMnx 2.x (S1.9). bbox order is (west, south, east, north) (verified, osmnx 2.1.1)."""
import logging
import re
import time

import geopandas as gpd
import networkx as nx
import osmnx as ox
import requests
from shapely.geometry import box

log = logging.getLogger(__name__)

# Public Overpass endpoints, tried in turn. Measured 17 Oct: overpass-api.de answers but queues every request ~30 s
# ("at capacity"); private.coffee was fastest (8 s for 3 MB, data ~3 months old) at 16:00 and returned 500 by 18:00;
# z.overpass-api.de is overpass-api.de's second server; maps.mail.ru (504), kumi.systems (500), osm.jp, openstreetmap.ru
# and .fr (403) were down or closed, so they are left out. Demo areas are prepared once and cached (S18), so live demos
# never depend on Overpass.
OVERPASS_URLS = ["https://overpass-api.de/api", "https://overpass.private.coffee/api", "https://z.overpass-api.de/api"]
ox.settings.overpass_rate_limit = False  # the status probe stalls under load; we back off ourselves
ox.settings.http_user_agent = "Pravah/0.1 (flood and landslide decision-support research prototype; non-commercial)"
# OSMnx uses this for both the HTTP read timeout and the Overpass server's [timeout:]; a dense 10 km box can need 2-4
# min on a busy server, so it stays at 240 s (120 s made such queries fail on every server)
ox.settings.requests_timeout = 240
BUNDLE_TIMEOUT_S = 300  # the single combined request (osm.bundle) is the largest query

POI_TAGS = {
    "amenity": True, "shop": True, "tourism": ["hotel", "guest_house", "hostel"],
    "public_transport": ["station"], "railway": ["station"],
    "building": ["school", "hospital", "temple", "public"],
}
WATERWAY_TAGS = {"waterway": ["river", "stream", "drain", "canal", "ditch"], "tunnel": ["culvert"]}
KEEP_COLS = ["name", "amenity", "shop", "tourism", "building", "public_transport", "railway",
             "waterway", "tunnel", "width", "capacity", "beds"]


def _retry(fn, *args, attempts: int = 4, **kwargs):
    for i in range(attempts):
        ox.settings.overpass_url = OVERPASS_URLS[i % len(OVERPASS_URLS)]
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # Overpass rate limits and timeouts
            if i == attempts - 1:
                raise
            log.warning("OSM call failed on %s (%s), retry %d", ox.settings.overpass_url, e, i + 1)
            time.sleep(2 * 2**i)


def graph(bbox: tuple[float, float, float, float], network_type: str) -> nx.MultiDiGraph:
    return _retry(ox.graph_from_bbox, bbox, network_type=network_type, simplify=True)


def _tidy(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.reset_index()
    gdf["osmid"] = gdf["element"].astype(str) + "/" + gdf["id"].astype(str)
    keep = ["osmid", "geometry"] + [c for c in KEEP_COLS if c in gdf.columns]
    gdf = gdf[keep].copy()
    for c in keep[2:]:  # parquet needs plain strings, OSM tags can be mixed types
        gdf[c] = gdf[c].astype("string")
    return gdf


def features(bbox: tuple[float, float, float, float], tags: dict) -> gpd.GeoDataFrame:
    try:
        return _tidy(_retry(ox.features_from_bbox, bbox, tags))
    except ox._errors.InsufficientResponseError:
        return gpd.GeoDataFrame(columns=["osmid", "geometry"], geometry="geometry", crs="EPSG:4326")


def _split(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    is_water = gdf["waterway"].notna() if "waterway" in gdf else gdf["osmid"].isna()
    if "tunnel" in gdf:
        is_water |= (gdf["tunnel"] == "culvert").fillna(False).astype(bool)
    return gdf[~is_water].reset_index(drop=True), gdf[is_water].reset_index(drop=True)


def pois_and_waterways(bbox: tuple[float, float, float, float]) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """One Overpass query for both tag sets, split afterwards."""
    return _split(features(bbox, {**POI_TAGS, **WATERWAY_TAGS}))


ROAD_BRIDGE_COLS = ["name", "highway", "construction", "access", "bridge", "layer", "disused", "abandoned"]
_NO_BRIDGES = lambda: gpd.GeoDataFrame(columns=["osmid", "geometry", *ROAD_BRIDGE_COLS], geometry="geometry", crs="EPSG:4326")  # noqa: E731


def _bridges(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.reset_index()
    gdf = gdf[(gdf["element"] == "way") & gdf.geometry.geom_type.eq("LineString")]
    gdf = gdf[gdf["highway"].notna()] if "highway" in gdf else gdf.iloc[0:0]
    gdf["osmid"] = "way/" + gdf["id"].astype(str)
    for c in ROAD_BRIDGE_COLS:
        gdf[c] = gdf[c].astype("string") if c in gdf else None
    return gdf[["osmid", "geometry", *ROAD_BRIDGE_COLS]].reset_index(drop=True)


def bridge_ways(bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Road and footway bridges as OSM mapped them (one way per span or carriageway), before graph simplification
    merges each span into the roads on either side. Railway, aqueduct and pipeline bridges are left out."""
    try:
        return _bridges(_retry(ox.features_from_bbox, bbox, {"bridge": True}))
    except ox._errors.InsufficientResponseError:
        return _NO_BRIDGES()


# ---------- everything in one request (17 Oct) ----------
# Each Overpass request waits its turn in the public server's queue (~30 s on 17 Oct, often minutes), and an area used
# five (walk roads, drive roads, bridges, places, waterways; walk and drive are almost the same ways). One request now
# brings all of it; the walk and drive networks are cut from it here with OSMnx's own filters and built with OSMnx's
# own steps (graph_from_polygon: 500 m buffer, truncate, largest component, simplify, truncate, street counts).
_FILTER = re.compile(r'\["([^"]+)"(?:(!?~)"([^"]+)")?\]')


def _passes(tags: dict, flt: list[tuple[str, str, str]]) -> bool:
    """An Overpass tag filter applied locally: ["k"] present, ["k"~"re"] matches, ["k"!~"re"] absent or not matching."""
    for k, op, rx in flt:
        v = tags.get(k)
        if not op:
            if v is None:
                return False
        elif op == "~":
            if v is None or not re.search(rx, v):
                return False
        elif v is not None and re.search(rx, v):
            return False
    return True


class QueryTooBig(RuntimeError):
    """Overpass ran the query and gave up (timeout or memory): the same query fails on every mirror."""


def _post(query: str, attempts: int = 4) -> dict:
    """POST to the Overpass mirrors in turn, with back-off (OSMnx's own request retries a busy server forever). A query
    the server ran out of time or memory on is not retried: the caller falls back to smaller requests."""
    for i in range(attempts):
        url = OVERPASS_URLS[i % len(OVERPASS_URLS)]
        try:
            r = requests.post(url + "/interpreter", data={"data": query}, timeout=BUNDLE_TIMEOUT_S + 30,
                              headers={"User-Agent": ox.settings.http_user_agent, "Accept-Encoding": "gzip"})
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                j = r.json()
                if "remark" in j and "runtime error" in str(j["remark"]):
                    raise QueryTooBig(str(j["remark"])[:160])
                return j
            raise RuntimeError(f"HTTP {r.status_code}")
        except QueryTooBig:
            raise
        except Exception as e:
            if i == attempts - 1:
                raise
            log.warning("Overpass %s failed (%s), retry %d", url, e, i + 1)
            time.sleep(3 * 2**i)
    raise RuntimeError("unreachable")


def _network(elements: list[dict], kind: str, poly, poly_buff) -> nx.MultiDiGraph:
    flt = [(k, op, rx) for k, op, rx in _FILTER.findall(ox._overpass._get_network_filter(kind))]
    ways = [e for e in elements if e["type"] == "way" and _passes(e.get("tags", {}), flt)]
    ids = {n for w in ways for n in w["nodes"]}
    nodes = [e for e in elements if e["type"] == "node" and e["id"] in ids]
    # OSMnx's builders consume the elements they are given (keys are popped), so each gets its own copies
    G_buff = ox.graph._create_graph([{"elements": [dict(x) for x in nodes + ways]}], kind in ox.settings.bidirectional_network_types)
    G_buff = ox.truncate.truncate_graph_polygon(G_buff, poly_buff)
    G_buff = ox.simplify_graph(ox.truncate.largest_component(G_buff))
    G = ox.truncate.largest_component(ox.truncate.truncate_graph_polygon(G_buff, poly))
    nx.set_node_attributes(G, values=ox.stats.count_streets_per_node(G_buff, nodes=G.nodes), name="street_count")
    return G


def _subset(els: list[dict], tags: dict) -> list[dict]:
    """The elements matching `tags` (OSMnx features syntax: {key: True | [values]}) plus the ways and nodes they are
    built from, as copies. Handing OSMnx the whole download made it build a shape for every road in the box before
    keeping the bridges or places: 5+ min in central Houston."""
    def hit(t: dict) -> bool:
        return any(k in t and (v is True or t[k] in (v if isinstance(v, list) else [v])) for k, v in tags.items())
    nodes = {e["id"]: e for e in els if e["type"] == "node"}
    ways = {e["id"]: e for e in els if e["type"] == "way"}
    top = [e for e in els if e.get("tags") and hit(e["tags"])]
    nid, wid = set(), set()
    for e in top:
        if e["type"] == "node":
            nid.add(e["id"])
        elif e["type"] == "way":
            wid.add(e["id"])
        else:
            for m in e.get("members", []):
                (wid if m["type"] == "way" else nid if m["type"] == "node" else set()).add(m["ref"])
    for w in wid:
        nid.update(ways[w]["nodes"] if w in ways else [])
    rel = [e for e in top if e["type"] == "relation"]
    return [dict(nodes[i]) for i in nid if i in nodes] + [dict(ways[i]) for i in wid if i in ways] + [dict(r) for r in rel]


def _selector(key: str, v) -> str:
    """OSMnx features tag syntax -> an Overpass selector: True = any value, a list = one of these values."""
    if v is True:
        return f'nwr["{key}"]'
    vals = v if isinstance(v, list) else [v]
    return f'nwr["{key}"~"^({"|".join(re.escape(str(x)) for x in vals)})$"]'


def bundle(bbox: tuple[float, float, float, float]) -> dict:
    """Walk and drive networks, road bridges, places and waterways from ONE Overpass request:
    {"walk", "drive", "bridges", "pois", "waterways"}, each as the per-item functions above return it."""
    poly = box(*bbox)
    poly_proj, crs = ox.projection.project_geometry(poly)
    poly_buff, _ = ox.projection.project_geometry(poly_proj.buffer(500), crs=crs, to_latlong=True)
    w, s, e, n = poly_buff.bounds
    bb = f"({s:.6f},{w:.6f},{n:.6f},{e:.6f})"
    # all highways (walk and drive are cut locally) plus the place and waterway tags, generated from the same dicts the
    # separate requests use so the two paths cannot drift apart
    sel = ['way["highway"]'] + [_selector(k, v) for k, v in {**POI_TAGS, **WATERWAY_TAGS}.items()]
    q = f"[out:json][timeout:{BUNDLE_TIMEOUT_S}];(" + "".join(f"{x}{bb};" for x in sel) + ");(._;>;);out;"
    t0 = time.time()
    els = _post(q)["elements"]
    log.info("OSM bundle: %d elements in %.0f s", len(els), time.time() - t0)
    out = {"drive": _network(els, "drive", poly, poly_buff), "walk": _network(els, "walk", poly, poly_buff)}
    poi_tags = {**POI_TAGS, **WATERWAY_TAGS}
    try:
        out["bridges"] = _bridges(ox.features._create_gdf([{"elements": _subset(els, {"bridge": True})}], poly, {"bridge": True}))
    except ox._errors.InsufficientResponseError:
        out["bridges"] = _NO_BRIDGES()
    try:
        out["pois"], out["waterways"] = _split(_tidy(ox.features._create_gdf([{"elements": _subset(els, poi_tags)}], poly, poi_tags)))
    except ox._errors.InsufficientResponseError:
        empty = gpd.GeoDataFrame(columns=["osmid", "geometry"], geometry="geometry", crs="EPSG:4326")
        out["pois"], out["waterways"] = empty, empty.copy()
    return out


def buildings(bbox: tuple[float, float, float, float], crs: str) -> gpd.GeoDataFrame:
    """OpenStreetMap building footprints, the fallback where Google Open Buildings has no coverage (e.g. Japan, Europe,
    North America). Height from the `height` tag, else `building:levels` x 3 m; NaN when neither is mapped."""
    import numpy as np
    try:
        gdf = _retry(ox.features_from_bbox, bbox, {"building": True})
    except ox._errors.InsufficientResponseError:
        gdf = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].reset_index(drop=True)

    def num(col):
        if col not in gdf:
            return np.full(len(gdf), np.nan)
        return gdf[col].astype(str).str.extract(r"([0-9]+(?:\.[0-9]+)?)")[0].astype(float).to_numpy()
    h = num("height")
    h = np.where(np.isfinite(h), h, num("building:levels") * 3.0)
    out = gpd.GeoDataFrame({"geometry": gdf.geometry.values}, geometry="geometry", crs="EPSG:4326").to_crs(crs)
    out["area_m2"] = out.geometry.area
    out["confidence"] = 1.0
    out["height_m"] = np.where((h > 0) & (h < 400), h, np.nan)
    out["presence_2023"], out["presence_2016"] = 1.0, np.nan
    out = out[out["area_m2"] >= 10].reset_index(drop=True)
    out["bid"] = [f"o{i}" for i in range(len(out))]
    return out[["bid", "geometry", "area_m2", "confidence", "height_m", "presence_2023", "presence_2016"]]
