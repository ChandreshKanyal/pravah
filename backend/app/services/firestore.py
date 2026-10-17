from datetime import datetime, timezone
from functools import lru_cache

from google.cloud import firestore

from app.config import get_settings


# Firestore rejects an array directly inside an array (e.g. [[lon, lat], ...] corners). Inner arrays are wrapped as
# {"_a": [...]} on write and unwrapped on read, so callers keep plain nested lists and old documents read unchanged.
_WRAP = "_a"


def encode(o):
    if isinstance(o, dict):
        return {k: encode(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [{_WRAP: encode(x)} if isinstance(x, (list, tuple)) else encode(x) for x in o]
    return o


def decode(o):
    if isinstance(o, dict):
        if len(o) == 1 and _WRAP in o and isinstance(o[_WRAP], list):
            return decode(o[_WRAP])
        return {k: decode(v) for k, v in o.items()}
    if isinstance(o, list):
        return [decode(x) for x in o]
    return o


@lru_cache
def get_db() -> firestore.Client:
    return firestore.Client(project=get_settings().google_cloud_project)


def ping() -> bool:
    ref = get_db().collection("health").document("ping")
    stamp = datetime.now(timezone.utc).isoformat()
    ref.set({"ts": stamp})
    return ref.get().to_dict().get("ts") == stamp


def set_aoi(aoi_id: str, data: dict) -> None:
    get_db().collection("aois").document(aoi_id).set(data, merge=True)


def update_aoi(aoi_id: str, fields: dict) -> None:
    """fields may use dotted paths, e.g. {"status.terrain": "ready"}."""
    get_db().collection("aois").document(aoi_id).update(fields)


def get_aoi(aoi_id: str) -> dict | None:
    snap = get_db().collection("aois").document(aoi_id).get()
    return decode(snap.to_dict()) if snap.exists else None


def set_doc(collection: str, doc_id: str, data: dict) -> None:
    get_db().collection(collection).document(doc_id).set(encode(data))


def merge_doc(collection: str, doc_id: str, data: dict) -> None:
    get_db().collection(collection).document(doc_id).set(encode(data), merge=True)


def get_doc(collection: str, doc_id: str) -> dict | None:
    snap = get_db().collection(collection).document(doc_id).get()
    return decode(snap.to_dict()) if snap.exists else None


def query(collection: str, **equals) -> list[dict]:
    """Documents whose fields equal the given values (simple AND of equality filters)."""
    from google.cloud.firestore_v1.base_query import FieldFilter
    q = get_db().collection(collection)
    for k, v in equals.items():
        q = q.where(filter=FieldFilter(k, "==", v))
    return [decode(d.to_dict()) for d in q.stream()]
