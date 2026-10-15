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
