"""S11 endpoints: India-wide historical layers and per-AOI incidents."""
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.services import history

router = APIRouter()


@router.get("/api/history/india")
def india():
    return {"gfd_tiles": history.gfd_tiles(), "landslides": history.glc_india(),
            "labels": {"gfd": "Observed floods 2000-2018 (Global Flood Database, MODIS)",
                       "glc": "Reported landslides 1970-2019 (NASA GLC)"},
            "note": "Historical incidents, not predictions"}


@router.get("/api/history/aoi/{aoi_id}")
async def aoi(aoi_id: str, web: bool = False, refresh: bool = False):
    try:
        return await run_in_threadpool(history.aoi_history, aoi_id, web, refresh)
    except KeyError as e:
        raise HTTPException(404, str(e))
