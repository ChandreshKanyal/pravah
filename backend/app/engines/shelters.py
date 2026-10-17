"""Shelter and medical candidates with capacities (S7.5-S7.6). Shelters are "reachable in this scenario", never "safe"."""
import math

import geopandas as gpd
import numpy as np
from scipy.spatial import cKDTree

SHELTER_AMENITIES = {"school", "college", "university", "community_centre", "townhall", "social_facility"}
WORSHIP = "place_of_worship"
MEDICAL = {"hospital", "clinic"}
DEFAULT_AREA_M2 = 200.0
USABLE_FRACTION = 0.6
MIN_OSM_SHELTERS = 5
MAX_CANDIDATES = 10


def clean(v) -> str:
    """OSM tag value as a plain string ('' for missing/NA)."""
    if v is None:
        return ""
    try:
        if v != v or str(v) in ("<NA>", "nan", "None"):
            return ""
    except TypeError:  # pd.NA comparisons
        return ""
    return str(v)


def capacity(area_m2: float, floors: int, sqm_per_person: float = 3.5) -> int:
    """floor(area x floors x 0.6 / m2 per person); 3.5 m2 is the Sphere minimum covered space."""
    return int(math.floor(area_m2 * max(1, floors) * USABLE_FRACTION / sqm_per_person))


def _match_building(geom, bld: gpd.GeoDataFrame, tree: cKDTree | None, cx: np.ndarray, cy: np.ndarray):
    """Nearest Open Buildings footprint within 30 m of the POI (index or None)."""
    if tree is None:
        return None
    p = geom.centroid
    d, i = tree.query([p.x, p.y], distance_upper_bound=30.0)
    return int(i) if np.isfinite(d) else None


def from_pois(pois: gpd.GeoDataFrame, bld: gpd.GeoDataFrame) -> tuple[list[dict], list[dict]]:
    """(shelters, medical) from OSM POIs (both GeoDataFrames in the grid CRS). Capacity is filled later."""
    tree, cx, cy = None, np.array([]), np.array([])
    if len(bld):
        c = bld.geometry.centroid
        cx, cy = c.x.to_numpy(), c.y.to_numpy()
        tree = cKDTree(np.column_stack([cx, cy]))
    shelters, medical = [], []
    for _, p in pois.iterrows():
        amenity = clean(p.get("amenity"))
        if amenity not in SHELTER_AMENITIES | MEDICAL | {WORSHIP}:
            continue
        geom = p.geometry
        j = _match_building(geom, bld, tree, cx, cy)
        floors = int(bld.iloc[j]["floors"]) if j is not None else 1
        if geom.geom_type in ("Polygon", "MultiPolygon") and geom.area > 0:
            area, conf = float(geom.area), "medium"
        elif j is not None:
            area, conf = float(bld.iloc[j]["area_m2"]), "medium"
        else:
            area, conf = DEFAULT_AREA_M2, "low"
        rec = {"name": clean(p.get("name")) or amenity.replace("_", " ").title(), "kind": amenity,
               "x": float(geom.centroid.x), "y": float(geom.centroid.y), "area_m2": round(area, 1),
               "floors": floors, "capacity_confidence": conf, "osm_id": clean(p.get("osmid")), "note": ""}
        if amenity in MEDICAL:
            medical.append(rec)
        else:
            if amenity == WORSHIP:
                rec["note"] = "large hall, confirm with authority"
            shelters.append(rec)
    return shelters, medical


def candidate_large_buildings(bld: gpd.GeoDataFrame, hand: np.ndarray, slope_deg: np.ndarray,
                              in_aoi, n: int, min_spacing_m: float = 200.0) -> list[dict]:
    """Fallback when OSM has few shelters: biggest likely-pukka buildings on high, gently sloping ground (unverified)."""
    if n <= 0 or not len(bld):
        return []
    b = bld[bld["structure_class"].isin(["likely_pukka_multi_storey", "likely_pukka_low_rise"]) & (bld["area_m2"] >= 150)]
    r, c = b["row"].to_numpy(int), b["col"].to_numpy(int)
    ok = (hand[r, c] >= 5) & (np.nan_to_num(slope_deg[r, c], nan=90) <= 20) & in_aoi(b)
    b = b[ok].assign(score=lambda d: d["area_m2"] * d["floors"]).sort_values("score", ascending=False)
    picked: list[dict] = []
    for _, row in b.iterrows():
        x, y = row.geometry.centroid.x, row.geometry.centroid.y
        if any(math.hypot(x - q["x"], y - q["y"]) < min_spacing_m for q in picked):
            continue
        picked.append({"name": f"Large building {row['bid']}", "kind": "candidate_large_building", "x": float(x),
                       "y": float(y), "area_m2": round(float(row["area_m2"]), 1), "floors": int(row["floors"]),
                       "capacity_confidence": "low", "osm_id": "", "bid": row["bid"],
                       "note": "unverified candidate: large building, confirm with authority"})
        if len(picked) >= n:
            break
    return picked
