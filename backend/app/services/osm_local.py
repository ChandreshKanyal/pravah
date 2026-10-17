"""India's OpenStreetMap data kept with us: 0.1 degree tiles in our bucket (scripts/build_osm_tiles.py, from the Geofabrik
India extract), read instead of the public Overpass server, which took 30 s to 15 min per area on 17-18 Oct. Returns
the same element list an Overpass query gives (nodes with lat/lon, ways with node refs and tags), so osm.bundle builds
roads, bridges, places and waterways from it unchanged. Coverage is the Geofabrik India boundary (app/data/india.poly),
which is also Pravah's service area. Data: OpenStreetMap contributors, ODbL."""
import gzip
import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from shapely.geometry import Polygon, box
from shapely.prepared import prep

from app.services import storage

log = logging.getLogger(__name__)
TILE = 0.1
PREFIX = "osm_tiles/india"
POLY = Path(__file__).resolve().parents[1] / "data" / "india.poly"


@lru_cache(maxsize=1)
def india():
    """The Geofabrik India boundary (Osmosis .poly: one ring of lon lat lines between a header and END)."""
    pts = []
    for line in POLY.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                pts.append((float(parts[0]), float(parts[1])))
            except ValueError:
                pass
    return prep(Polygon(pts).buffer(0))


def covers(bbox) -> bool:
    """True when the whole box lies inside India (the service area and the extent of the tiles)."""
    return india().contains(box(*bbox))


def _tile(x: int, y: int) -> list[dict]:
    from google.api_core.exceptions import NotFound
    try:
        raw = storage._bucket().blob(f"{PREFIX}/{x}_{y}.jsonl.gz").download_as_bytes()
    except NotFound:  # sea, or land with no mapped roads
        return []
    return [json.loads(line) for line in gzip.decompress(raw).splitlines() if line]


def elements(bbox) -> list[dict]:
    """Overpass-style elements for ways with a node inside `bbox` (all their nodes included, like Overpass `>`), and
    tagged nodes inside it."""
    w, s, e, n = bbox
    keys = [(x, y) for x in range(math.floor(w / TILE), math.floor(e / TILE) + 1)
            for y in range(math.floor(s / TILE), math.floor(n / TILE) + 1)]
    with ThreadPoolExecutor(min(8, len(keys))) as ex:
        tiles = list(ex.map(lambda k: _tile(*k), keys))
    inside = lambda lat, lon: s <= lat <= n and w <= lon <= e  # noqa: E731
    ways: dict[int, dict] = {}
    nodes: dict[int, dict] = {}
    for recs in tiles:
        for r in recs:
            if "w" in r:
                if r["w"] in ways or not any(inside(p[1], p[2]) for p in r["n"]):
                    continue
                ways[r["w"]] = {"type": "way", "id": r["w"], "nodes": [p[0] for p in r["n"]], "tags": r["t"]}
                for ref, lat, lon in r["n"]:
                    nodes.setdefault(ref, {"type": "node", "id": ref, "lat": lat, "lon": lon})
            elif inside(*r["l"]):
                nd = nodes.setdefault(r["n"], {"type": "node", "id": r["n"], "lat": r["l"][0], "lon": r["l"][1]})
                nd["tags"] = r["t"]
    log.info("OSM tiles: %d tiles, %d ways, %d nodes", len(keys), len(ways), len(nodes))
    return list(nodes.values()) + list(ways.values())
