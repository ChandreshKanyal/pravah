"""One model for every area (17 Oct): add the street-waterlogging layers (hollows and drain candidates) to areas
prepared in "river" mode before the switch was removed. Usage: backend/.venv/bin/python scripts/backfill_waterlogging.py [aoi_id ...]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.aoi import AOI  # noqa: E402
from app.pipeline.prepare_area import _urban  # noqa: E402
from app.services import firestore as fs, storage  # noqa: E402

ids = [a for a in sys.argv[1:] if not a.startswith("--")] or [d.id for d in fs.get_db().collection("aois").stream()]
for aoi_id in ids:
    if storage.exists(aoi_id, "pluvial.npz") and "--force" not in sys.argv:
        print(aoi_id, "already has waterlogging layers")
        continue
    doc = fs.get_aoi(aoi_id) or {}
    if not storage.exists(aoi_id, "grid.json") and not doc.get("grid"):
        print(aoi_id, "not prepared; skipped")
        continue
    aoi = AOI(aoi_id=aoi_id, name=doc.get("name") or aoi_id, bbox=tuple(doc["bbox"]), mode=doc.get("mode") or "auto")
    warnings: list[str] = []
    meta: dict = {}
    _urban(aoi, storage.load_grid(aoi_id), warnings, meta)
    fs.update_aoi(aoi_id, {"status.urban": "ready", "meta.urban": meta.get("urban")})
    print(aoi_id, doc.get("name"), meta.get("urban"), warnings)
