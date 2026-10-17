"""One-time: cut a Geofabrik OpenStreetMap extract (India) into 0.1 degree tiles of exactly what area preparation reads
(roads, waterways, places, points of interest), so preparing an area reads 1-4 tiles from our bucket instead of waiting
on the public Overpass server (30 s to 15 min, 17-18 Oct). Needs pyosmium (`uv pip install osmium`), local only.

    backend/.venv/bin/python scripts/build_osm_tiles.py india.osm.pbf out_dir [shards shard index]
    gcloud storage rsync out_dir gs://<bucket>/osm_tiles/india

On a laptop the node-location index (4 GB for India) lives on disk and lookups wait on it (~2,000 ways/s). On a
high-memory machine run several shards at once (`shards` processes, `shard` = 0..shards-1, index "flex_mem"), each
writing its own out_dir, then concatenate each tile's files (gzip members join cleanly).

Each tile is gzipped JSON lines: {"w": id, "t": tags, "n": [[ref, lat, lon], ...]} for a way (in every tile one of its
nodes falls in) and {"n": id, "t": tags, "l": [lat, lon]} for a tagged node. Multipolygon relations are not kept (the
Overpass path keeps them; a few large POI areas and riverbank polygons differ). Data: OpenStreetMap contributors, ODbL.
"""
import gzip
import json
import math
import os
import sys
import time
from collections import defaultdict

import osmium

# the tag sets of backend/app/services/osm.py, copied so this runs without the backend (tests/test_osm_filter.py
# checks they still match)
PLACE_TAGS = {"place": ["city", "town", "village", "suburb", "hamlet", "neighbourhood", "quarter", "locality", "isolated_dwelling"]}
POI_TAGS = {
    "amenity": True, "shop": True, "tourism": ["hotel", "guest_house", "hostel"],
    "public_transport": ["station"], "railway": ["station"],
    "building": ["school", "hospital", "temple", "public"],
}
WATERWAY_TAGS = {"waterway": ["river", "stream", "drain", "canal", "ditch"], "tunnel": ["culvert"]}

TILE = 0.1
KEYS = ["highway", "waterway", "tunnel", "amenity", "shop", "tourism", "public_transport", "railway", "building", "place"]
FEATURE_TAGS = {**POI_TAGS, **WATERWAY_TAGS, **PLACE_TAGS}
# tags nothing in Pravah reads (editing metadata, addresses, links): dropped to keep India's tiles small
DROP = ("source", "created_by", "note", "fixme", "FIXME", "is_in", "addr:", "check_date", "wikipedia", "wikidata",
        "brand", "contact:", "survey", "description", "image", "mapillary", "old_name", "alt_name", "website", "phone",
        "opening_hours", "email", "start_date", "tiger:", "ref:", "gnis:")


def slim(tags) -> dict:
    return {k: v for k, v in tags if not k.startswith(DROP) and not (k.startswith("name:") and k not in ("name:hi", "name:en"))}


def wanted(tags: dict, way: bool) -> bool:
    if way and "highway" in tags:
        return True
    for k, v in FEATURE_TAGS.items():
        if k in tags and (v is True or tags[k] in v):
            return True
    return False


def tile_of(lat: float, lon: float) -> tuple[int, int]:
    return math.floor(lon / TILE), math.floor(lat / TILE)


def main(pbf: str, out: str, shards: int = 1, shard: int = 0, index: str = "") -> None:
    os.makedirs(out, exist_ok=True)
    buf: dict[tuple[int, int], list[str]] = defaultdict(list)
    n_buf = 0

    def flush() -> None:  # each flush appends one gzip member per tile (a multi-member gzip reads as one file)
        nonlocal n_buf
        for (x, y), lines in buf.items():
            with open(os.path.join(out, f"{x}_{y}.jsonl.gz"), "ab") as f:
                f.write(gzip.compress("".join(lines).encode(), compresslevel=6))
        buf.clear()
        n_buf = 0

    t0, ways, nodes, bad = time.time(), 0, 0, 0
    fp = osmium.FileProcessor(pbf).with_locations(index or "sparse_file_array," + os.path.join(out, "..", "locations.idx"))
    fp = fp.with_filter(osmium.filter.KeyFilter(*KEYS))
    for o in fp:
        if o.is_node():
            if shard:  # tagged nodes are written by shard 0 only
                continue
            tags = dict(o.tags)
            if not wanted(tags, False) or not o.location.valid():
                continue
            lat, lon = o.location.lat, o.location.lon
            buf[tile_of(lat, lon)].append(json.dumps({"n": o.id, "t": slim(tags.items()), "l": [round(lat, 6), round(lon, 6)]}, separators=(",", ":")) + "\n")
            nodes += 1
            n_buf += 1
        elif o.is_way():
            if o.id % shards != shard:
                continue
            tags = dict(o.tags)
            if not wanted(tags, True):
                continue
            pts = [[n.ref, round(n.lat, 6), round(n.lon, 6)] for n in o.nodes if n.location.valid()]
            if len(pts) < 2:
                bad += 1
                continue
            line = json.dumps({"w": o.id, "t": slim(tags.items()), "n": pts}, separators=(",", ":")) + "\n"
            for t in {tile_of(p[1], p[2]) for p in pts}:
                buf[t].append(line)
                n_buf += 1
            ways += 1
            if ways % 500_000 == 0:
                print(f"{ways:,} ways, {nodes:,} nodes, {bad} without locations, {time.time() - t0:.0f} s", flush=True)
        if n_buf > 1_500_000:
            flush()
    flush()
    print(f"done: {ways:,} ways, {nodes:,} tagged nodes, {bad} ways without locations, {time.time() - t0:.0f} s", flush=True)
    files = [f for f in os.listdir(out) if f.endswith(".jsonl.gz")]
    print(f"{len(files)} tiles, {sum(os.path.getsize(os.path.join(out, f)) for f in files) / 1e6:.0f} MB gzipped", flush=True)

if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], int(a[2]) if len(a) > 2 else 1, int(a[3]) if len(a) > 3 else 0, a[4] if len(a) > 4 else "")
