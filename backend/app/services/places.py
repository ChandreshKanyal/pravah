"""Settlement names for human-readable labels ("near Ratura") instead of model ids. Source: OpenStreetMap place=*
nodes and areas (ODbL, cacheable), stored once per AOI as places.json. Google geocoding is never used for this,
because Maps content may not be cached or used as analysis input (SPEC 2)."""
import logging
import math

from app.engines.grid import lonlat_bounds
from app.services import osm, storage

log = logging.getLogger(__name__)

PLACE_KINDS = osm.PLACE_TAGS["place"]
# a bigger place wins over a slightly nearer hamlet: effective distance = distance / weight
WEIGHT = {"city": 3.0, "town": 2.5, "suburb": 1.8, "village": 1.6, "quarter": 1.3, "neighbourhood": 1.2, "hamlet": 1.0,
          "locality": 0.8, "isolated_dwelling": 0.6}
DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def from_gdf(gdf) -> list[dict]:
    """[{name, name_hi, kind, lon, lat}] from OSM place features (named ones only)."""
    out = []
    if gdf is not None and len(gdf):
        for _, r in gdf.iterrows():
            name = r.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            c = r.geometry.centroid
            hi = r.get("name:hi")
            out.append({"name": name.strip(), "name_hi": hi.strip() if isinstance(hi, str) else "",
                        "kind": str(r.get("place") or "locality"), "lon": round(c.x, 6), "lat": round(c.y, 6)})
    return out


def _fetch(aoi_id: str, grid=None) -> list[dict]:
    import osmnx as ox
    grid = grid or storage.load_grid(aoi_id)
    try:
        gdf = osm._retry(ox.features_from_bbox, lonlat_bounds(grid), osm.PLACE_TAGS)
    except ox._errors.InsufficientResponseError:  # OSM has no places here: remember that
        gdf = None
    except Exception as e:  # Overpass down: no cache, so the next run tries again
        log.info("places unavailable for %s: %s", aoi_id, e)
        return []
    out = from_gdf(gdf)
    storage.put_json(aoi_id, "places.json", out)
    return out


_fetching: set[str] = set()


def area_places(aoi_id: str, grid=None, wait: bool = False) -> list[dict]:
    """[{name, name_hi, kind, lon, lat}] for the AOI grid extent, cached in GCS (written at prep time with the roads).
    Without a cache (areas prepared before 18 Oct) nothing waits on Overpass: [] now and a background fetch for next
    time (a first run once waited 6.5 min on a struggling server). `wait=True` fetches in place."""
    if storage.exists(aoi_id, "places.json"):
        return storage.get_json(aoi_id, "places.json")
    if wait:
        return _fetch(aoi_id, grid)
    if aoi_id not in _fetching:
        import threading
        _fetching.add(aoi_id)

        def bg() -> None:
            try:
                _fetch(aoi_id, grid)
            finally:
                _fetching.discard(aoi_id)
        threading.Thread(target=bg, daemon=True).start()
    return []


def _dist_m(lon1, lat1, lon2, lat2) -> float:
    kx = 111320 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lon2 - lon1) * kx, (lat2 - lat1) * 110540)


def nearest(places: list[dict], lon: float, lat: float, max_m: float = 3000) -> dict | None:
    best, score = None, float("inf")
    for p in places:
        d = _dist_m(p["lon"], p["lat"], lon, lat)
        s = d / WEIGHT.get(p["kind"], 1.0)
        if d <= max_m and s < score:
            best, score = {**p, "dist_m": d}, s
    if best:
        ang = math.degrees(math.atan2((lon - best["lon"]) * math.cos(math.radians(lat)), lat - best["lat"])) % 360
        best["dir"] = DIRS[int((ang + 22.5) // 45) % 8]  # direction of the point FROM the place
    return best


_GENERIC = {"temple", "mandir", "school", "church", "mosque", "masjid", "hospital", "college", "office", "building"}


def area_landmarks(aoi_id: str) -> list[dict]:
    """Named schools, temples, halls and hospitals (the area's shelters and medical points) to tell apart places
    inside one town, where OSM has no neighbourhood names."""
    out = []
    for name in ("shelters.json", "medical.json"):
        if storage.exists(aoi_id, name):
            for x in storage.get_json(aoi_id, name):
                n = (x.get("name") or "").strip()
                if n and n.lower() not in _GENERIC and not n.lower().startswith(("large building", "unnamed", "candidate")):
                    out.append({"name": n, "lon": x["lon"], "lat": x["lat"]})
    return out


def label(places: list[dict], lon: float, lat: float, hindi: bool = False, landmarks: list[dict] | None = None) -> str:
    """'Ratura' within 400 m (inside a town: within 1.5 km), else 'near Ratura (1.2 km NE)' up to 3 km; a named
    landmark within 350 m is appended ('Rudraprayag, near Govt Inter College'). '' when nothing is close."""
    p = nearest(places, lon, lat)
    lm = None
    if landmarks:
        d, lm = min(((_dist_m(x["lon"], x["lat"], lon, lat), x) for x in landmarks), key=lambda t: t[0])
        lm = lm["name"] if d <= 350 else None
    if not p:
        return f"near {lm}" if lm else ""
    name = (p["name_hi"] or p["name"]) if hindi else p["name"]
    if lm:  # "Jankalyan Hospital, Rudraprayag" next to "Rudraprayag" -> "Jankalyan Hospital"
        for t in (p["name"], p["name_hi"]):
            if t and lm.lower().endswith(t.lower()) and len(lm) > len(t) + 3:
                lm = lm[: -len(t)].rstrip(" ,-")
    inside = p["dist_m"] <= 400 or (p["kind"] in ("town", "city") and p["dist_m"] <= 1500)
    base = name if inside else f"near {name} ({p['dist_m'] / 1000:.1f} km {p['dir']})"
    return f"{base}, near {lm}" if lm and inside else base
