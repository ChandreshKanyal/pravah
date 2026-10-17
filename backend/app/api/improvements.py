"""Pre-monsoon improvements per area (pipeline/improvements.py): the list, its image clips, and a refresh."""
import re

from fastapi import APIRouter, Depends, HTTPException, Response

from app.auth import require
from app.pipeline import improvements as imp
from app.services import firestore as fs, storage

router = APIRouter()


@router.get("/api/aoi/{aoi_id}/improvements")
def improvements(aoi_id: str):
    """{state: none | running | ready | error, ...improvements.json}."""
    doc = fs.get_aoi(aoi_id)
    if not doc:
        raise HTTPException(404, "Unknown AOI")
    st = (doc.get("status") or {})
    steps = {k: st.get(k) for k in imp.STEPS}
    if aoi_id in imp.RUNNING:  # only this process's jobs count: a "running" left by a restart is stale
        state = "running"
    elif storage.exists(aoi_id, "improvements.json"):
        return {"state": "ready", "steps": steps, **storage.get_json(aoi_id, "improvements.json")}
    elif "error" in steps.values():
        state = "error"
    else:
        state = "none"
    return {"state": state, "steps": steps}


@router.post("/api/aoi/{aoi_id}/improvements")
def improvements_refresh(aoi_id: str, user: dict = Depends(require("analyst"))):
    """Recompute in the background (about 1-2 minutes: satellite layers, web search, Gemini review)."""
    if not fs.get_aoi(aoi_id):
        raise HTTPException(404, "Unknown AOI")
    imp.start(aoi_id)
    return {"state": "running"}


@router.get("/api/aoi/{aoi_id}/improvements/img/{key}.png")
def improvement_image(aoi_id: str, key: str):
    if not re.fullmatch(r"[0-9a-f]{10}_[a-z]+", key):
        raise HTTPException(400, "Bad image key")
    from google.api_core.exceptions import NotFound
    try:  # one storage call per image (an exists check first doubled the round trips)
        data = storage.get_bytes(aoi_id, f"improvements/{key}.png")
    except NotFound:
        raise HTTPException(404, "No such image")
    return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
