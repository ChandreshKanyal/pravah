from fastapi import APIRouter

from app.services import earth_engine, firestore, gemini

router = APIRouter()


def _check(fn) -> bool:
    try:
        return bool(fn())
    except Exception as e:  # report failure, never raise from health
        print(f"health check failed: {fn.__module__}.{fn.__name__}: {e!r}")
        return False


@router.get("/api/health")
def health():
    ee_ok = _check(earth_engine.ping)
    vertex_ok = _check(lambda: gemini.generate("Reply with the single word: ok").strip())
    fs_ok = _check(firestore.ping)
    return {"ok": ee_ok and vertex_ok and fs_ok, "ee": ee_ok, "vertex": vertex_ok, "firestore": fs_ok}
