"""OpenStreetMap via OSMnx 2.x (S1.9). bbox order is (west, south, east, north) (verified, osmnx 2.1.1)."""
import logging
import time

import geopandas as gpd
import networkx as nx
import osmnx as ox

log = logging.getLogger(__name__)

# Public Overpass endpoints; each retry moves to the next. private.coffee was fastest on 15 Oct but on 16 Oct began
# refusing automated clients, so it is tried last. Demo areas are prepared once and cached (S18), so live demos
# never depend on Overpass.
OVERPASS_URLS = ["https://overpass-api.de/api", "https://maps.mail.ru/osm/tools/overpass/api",
                 "https://overpass.kumi.systems/api", "https://overpass.private.coffee/api"]
ox.settings.overpass_rate_limit = False  # the status probe stalls under load; we back off ourselves
ox.settings.http_user_agent = "Pravah/0.1 (flood and landslide decision-support research prototype; non-commercial)"
ox.settings.requests_timeout = 240

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
            log.warning("OSM call failed (%s), retry %d", e, i + 1)
            time.sleep(2 * 2**i)


def graph(bbox: tuple[float, float, float, float], network_type: str) -> nx.MultiDiGraph:
    return _retry(ox.graph_from_bbox, bbox, network_type=network_type, simplify=True)


def features(bbox: tuple[float, float, float, float], tags: dict) -> gpd.GeoDataFrame:
    try:
        gdf = _retry(ox.features_from_bbox, bbox, tags)
    except ox._errors.InsufficientResponseError:
        return gpd.GeoDataFrame(columns=["osmid", "geometry"], geometry="geometry", crs="EPSG:4326")
    gdf = gdf.reset_index()
    gdf["osmid"] = gdf["element"].astype(str) + "/" + gdf["id"].astype(str)
    keep = ["osmid", "geometry"] + [c for c in KEEP_COLS if c in gdf.columns]
    gdf = gdf[keep].copy()
    for c in keep[2:]:  # parquet needs plain strings, OSM tags can be mixed types
        gdf[c] = gdf[c].astype("string")
    return gdf


def pois_and_waterways(bbox: tuple[float, float, float, float]) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """One Overpass query for both tag sets, split afterwards."""
    gdf = features(bbox, {**POI_TAGS, **WATERWAY_TAGS})
    is_water = gdf["waterway"].notna() if "waterway" in gdf else gdf["osmid"].isna()
    if "tunnel" in gdf:
        is_water |= (gdf["tunnel"] == "culvert").fillna(False).astype(bool)
    return gdf[~is_water].reset_index(drop=True), gdf[is_water].reset_index(drop=True)


ROAD_BRIDGE_COLS = ["name", "highway", "construction", "access", "bridge", "layer", "disused", "abandoned"]


def bridge_ways(bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Road and footway bridges as OSM mapped them (one way per span or carriageway), before graph simplification
    merges each span into the roads on either side. Railway, aqueduct and pipeline bridges are left out."""
    try:
        gdf = _retry(ox.features_from_bbox, bbox, {"bridge": True})
    except ox._errors.InsufficientResponseError:
        return gpd.GeoDataFrame(columns=["osmid", "geometry", *ROAD_BRIDGE_COLS], geometry="geometry", crs="EPSG:4326")
    gdf = gdf.reset_index()
    gdf = gdf[(gdf["element"] == "way") & gdf.geometry.geom_type.eq("LineString")]
    gdf = gdf[gdf["highway"].notna()] if "highway" in gdf else gdf.iloc[0:0]
    gdf["osmid"] = "way/" + gdf["id"].astype(str)
    for c in ROAD_BRIDGE_COLS:
        gdf[c] = gdf[c].astype("string") if c in gdf else None
    return gdf[["osmid", "geometry", *ROAD_BRIDGE_COLS]].reset_index(drop=True)


ROAD_BRIDGE_COLS = ["name", "highway", "construction", "access", "bridge", "layer", "disused", "abandoned"]


def bridge_ways(bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Road and footway bridges as OSM mapped them (one way per span or carriageway), before graph simplification
    merges each span into the roads on either side. Railway, aqueduct and pipeline bridges are left out."""
    try:
        gdf = _retry(ox.features_from_bbox, bbox, {"bridge": True})
    except ox._errors.InsufficientResponseError:
        return gpd.GeoDataFrame(columns=["osmid", "geometry", *ROAD_BRIDGE_COLS], geometry="geometry", crs="EPSG:4326")
    gdf = gdf.reset_index()
    gdf = gdf[(gdf["element"] == "way") & gdf.geometry.geom_type.eq("LineString")]
    gdf = gdf[gdf["highway"].notna()] if "highway" in gdf else gdf.iloc[0:0]
    gdf["osmid"] = "way/" + gdf["id"].astype(str)
    for c in ROAD_BRIDGE_COLS:
        gdf[c] = gdf[c].astype("string") if c in gdf else None
    return gdf[["osmid", "geometry", *ROAD_BRIDGE_COLS]].reset_index(drop=True)


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
