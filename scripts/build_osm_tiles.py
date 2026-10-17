"""One-time: cut a Geofabrik OpenStreetMap extract (India) into 0.1 degree tiles of exactly what area preparation reads
(roads, waterways, places, points of interest), so preparing an area reads 1-4 tiles from our bucket instead of waiting
on the public Overpass server (30 s to 15 min, 17-18 Oct). Needs pyosmium (`uv pip install osmium`), local only.

    backend/.venv/bin/python scripts/build_osm_tiles.py india.osm.pbf out_dir
    gcloud storage cp -r out_dir/* gs://<bucket>/osm_tiles/india/

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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.services.osm import PLACE_TAGS, POI_TAGS, WATERWAY_TAGS  # noqa: E402

TILE = 0.1
KEYS = ["highway", "waterway", "tunnel", "amenity", "shop", "tourism", "public_transport", "railway", "building", "place"]
FEATURE_TAGS = {**POI_TAGS, **WATERWAY_TAGS, **PLACE_TAGS}


def wanted(tags: dict, way: bool) -> bool:
    if way and "highway" in tags:
        return True
    for k, v in FEATURE_TAGS.items():
        if k in tags and (v is True or tags[k] in v):
            return True
    return False


def tile_of(lat: float, lon: float) -> tuple[int, int]:
    return math.floor(lon / TILE), math.floor(lat / TILE)


def main(pbf: str, out: str) -> None:
    os.makedirs(out, exist_ok=True)
    buf: dict[tuple[int, int], list[str]] = defaultdict(list)
    n_buf = 0

    def flush() -> None:
        nonlocal n_buf
        for (x, y), lines in buf.items():
            with open(os.path.join(out, f"{x}_{y}.jsonl"), "a") as f:
                f.write("".join(lines))
        buf.clear()
        n_buf = 0

    t0, ways, nodes, bad = time.time(), 0, 0, 0
    fp = osmium.FileProcessor(pbf).with_locations("sparse_file_array," + os.path.join(out, "..", "locations.idx"))
    fp = fp.with_filter(osmium.filter.KeyFilter(*KEYS))
    for o in fp:
        if o.is_node():
            tags = dict(o.tags)
            if not wanted(tags, False) or not o.location.valid():
                continue
            lat, lon = o.location.lat, o.location.lon
            buf[tile_of(lat, lon)].append(json.dumps({"n": o.id, "t": tags, "l": [round(lat, 7), round(lon, 7)]}, separators=(",", ":")) + "\n")
            nodes += 1
            n_buf += 1
        elif o.is_way():
            tags = dict(o.tags)
            if not wanted(tags, True):
                continue
            pts = [[n.ref, round(n.lat, 7), round(n.lon, 7)] for n in o.nodes if n.location.valid()]
            if len(pts) < 2:
                bad += 1
                continue
            line = json.dumps({"w": o.id, "t": tags, "n": pts}, separators=(",", ":")) + "\n"
            for t in {tile_of(p[1], p[2]) for p in pts}:
                buf[t].append(line)
                n_buf += 1
            ways += 1
            if ways % 500_000 == 0:
                print(f"{ways:,} ways, {nodes:,} nodes, {bad} without locations, {time.time() - t0:.0f} s", flush=True)
        if n_buf > 400_000:
            flush()
    flush()
    print(f"done: {ways:,} ways, {nodes:,} tagged nodes, {bad} ways without locations, {time.time() - t0:.0f} s", flush=True)
    files = [f for f in os.listdir(out) if f.endswith(".jsonl")]
    for f in files:  # gzip every tile
        p = os.path.join(out, f)
        with open(p, "rb") as src, gzip.open(p + ".gz", "wb", compresslevel=6) as dst:
            dst.write(src.read())
        os.remove(p)
    print(f"{len(files)} tiles, {sum(os.path.getsize(os.path.join(out, f + '.gz')) for f in files) / 1e6:.0f} MB gzipped", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
