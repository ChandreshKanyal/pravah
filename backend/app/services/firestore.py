from datetime import datetime, timezone
from functools import lru_cache

from google.cloud import firestore

from app.config import get_settings


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
    return snap.to_dict() if snap.exists else None
