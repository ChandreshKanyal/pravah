"""S11 endpoints: India-wide historical layers and per-AOI incidents."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.auth import current_user
from app.services import history

router = APIRouter()


@router.get("/api/history/india")
def india():
    return {"gfd_tiles": history.gfd_tiles(),
            "labels": {"gfd": "Observed floods 2000-2018 (Global Flood Database, MODIS)"},
            "note": "Historical incidents, not predictions"}


_web_jobs: dict = {}


def _web_job(aoi_id: str, refresh: bool) -> None:
    try:
        history.aoi_history(aoi_id, True, refresh)
    finally:
        _web_jobs.pop(aoi_id, None)


@router.get("/api/history/aoi/{aoi_id}")
async def aoi(aoi_id: str, web: bool = False, refresh: bool = False, user: dict = Depends(current_user)):
    """Dataset incidents now; web leads (Gemini + Google Search, ~1 min) run in the background, beyond Firebase
    Hosting's 60 s rewrite budget, so `web=true` starts the job and the UI polls until `web` appears."""
    try:
        doc = await run_in_threadpool(history.aoi_history, aoi_id, False, refresh and not web)
    except KeyError as e:
        raise HTTPException(404, str(e))
    if web and ("web" not in doc or refresh):
        from app.auth import ROLES
        from app.config import get_settings
        if get_settings().auth_required and (not user["verified"] or ROLES.index(user["role"]) < ROLES.index("analyst")):
            raise HTTPException(401, "Sign in as an analyst to search the web")
        if aoi_id not in _web_jobs:
            import threading
            t = threading.Thread(target=_web_job, args=(aoi_id, refresh), daemon=True)
            _web_jobs[aoi_id] = t
            t.start()
        doc = {**doc, "web_status": "pending"}
    return doc
