"""Build bridges.json (real OSM bridge spans with deck heights, engines/bridges.py) for prepared areas.

Usage: backend/.venv/bin/python scripts/build_bridges.py [aoi_id ...]   (no ids: every prepared area)
New areas get this in prepare_area's network step; this backfills areas prepared before it existed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.pipeline.prepare_area import build_bridges  # noqa: E402
from app.services import firestore as fs, storage  # noqa: E402


def main(ids: list[str]) -> None:
    if not ids:
        ids = [a["aoi_id"] for a in fs.query("aois") if storage.exists(a["aoi_id"], "edges_walk.parquet")]
    for aoi_id in ids:
        warnings: list[str] = []
        meta = build_bridges(aoi_id, storage.load_grid(aoi_id), warnings)
        print(aoi_id, meta, warnings or "")


if __name__ == "__main__":
    main(sys.argv[1:])
