"""OpenStreetMap via OSMnx 2.x (S1.9). bbox order is (west, south, east, north) (verified, osmnx 2.1.1)."""
import logging
import time

import geopandas as gpd
import networkx as nx
import osmnx as ox

log = logging.getLogger(__name__)

# Public Overpass endpoints, fastest first (measured 2026-10-15: private.coffee 1.5 s, overpass-api.de 39.5 s
# for the same small query). Each retry moves to the next endpoint.
OVERPASS_URLS = ["https://overpass.private.coffee/api", "https://overpass-api.de/api"]
ox.settings.overpass_rate_limit = False  # the status probe stalls under load; we back off ourselves

POI_TAGS = {
    "amenity": True, "shop": True, "tourism": ["hotel", "guest_house", "hostel"],
    "public_transport": ["station"], "railway": ["station"],
    "building": ["school", "hospital", "temple", "public"],
}
WATERWAY_TAGS = {"waterway": ["river", "stream", "drain", "canal", "ditch"], "tunnel": ["culvert"]}
KEEP_COLS = ["name", "amenity", "shop", "tourism", "building", "public_transport", "railway",
             "waterway", "tunnel", "width", "capacity", "beds"]


def _retry(fn, *args, attempts: int = 3, **kwargs):
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
