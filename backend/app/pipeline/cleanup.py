"""Permanent deletion of runs and areas: Firestore documents and Cloud Storage files. The audit trail is kept (and
records the deletion). Archive is the reversible alternative."""
import logging

from app.services import firestore as fs
from app.services import storage

log = logging.getLogger(__name__)


def _delete_prefix(prefix: str) -> int:
    n = 0
    for blob in storage._bucket().list_blobs(prefix=prefix):
        blob.delete()
        n += 1
    return n


def _delete_where(collection: str, field: str, value: str) -> int:
    n = 0
    for d in fs.get_db().collection(collection).where(field, "==", value).stream():
        d.reference.delete()
        n += 1
    return n


def delete_run(run_id: str, reassign_default: bool = True) -> dict:
    """The run, its files, brief (and versions), 3D water model, public alert and drills. If it was its area's default,
    the newest remaining run becomes the default."""
    db = fs.get_db()
    doc = fs.get_doc("runs", run_id) or {}
    files = _delete_prefix(f"runs/{run_id}/")
    adv = fs.get_doc("advisories", run_id) or {}
    versions = int(adv.get("version") or 0)
    for v in range(1, versions + 3):  # immutable brief versions are stored as {run_id}_v{n}
        db.collection("advisory_versions").document(f"{run_id}_v{v}").delete()
    for coll in ("runs", "advisories", "flows", "alerts"):
        db.collection(coll).document(run_id).delete()
    drills = _delete_where("drills", "run_id", run_id)
    aoi_id = doc.get("aoi_id")
    if aoi_id:
        from app.api.aoi import _summary
        _summary.pop(run_id, None)
        aoi = fs.get_aoi(aoi_id) or {}
        if reassign_default and aoi.get("latest_run_id") == run_id:
            rest = [d.to_dict() for d in db.collection("runs").where("aoi_id", "==", aoi_id).select(["run_id", "created_at", "archived"]).stream()]
            rest = sorted((r for r in rest if not r.get("archived")), key=lambda r: str(r.get("created_at") or ""), reverse=True)
            fs.update_aoi(aoi_id, {"latest_run_id": rest[0]["run_id"] if rest else None})
    log.info("deleted run %s: %d files, %d brief versions, %d drills", run_id, files, versions, drills)
    return {"run_id": run_id, "aoi_id": aoi_id, "files": files, "drills": drills}


def delete_area(aoi_id: str) -> dict:
    """Every run of the area (as delete_run), the area's prepared data and its emulator, history and photos."""
    db = fs.get_db()
    runs = [d.id for d in db.collection("runs").where("aoi_id", "==", aoi_id).select(["run_id"]).stream()]
    for rid in runs:
        delete_run(rid, reassign_default=False)
    files = _delete_prefix(f"aoi/{aoi_id}/")
    for coll in ("emulators", "history_cache"):
        db.collection(coll).document(aoi_id).delete()
    photos = _delete_where("photos", "aoi_id", aoi_id)
    db.collection("aois").document(aoi_id).delete()
    log.info("deleted area %s: %d runs, %d files, %d photos", aoi_id, len(runs), files, photos)
    return {"aoi_id": aoi_id, "runs": len(runs), "files": files}
