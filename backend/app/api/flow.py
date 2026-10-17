"""2D water-flow model per run (pipeline/flow.py): status, start, and frames for the 3D view."""
from fastapi import APIRouter, Depends, HTTPException, Response
from google.api_core.exceptions import NotFound

from app.auth import require
from app.pipeline import flow
from app.services import firestore as fs, storage

router = APIRouter()


@router.get("/api/runs/{run_id}/flow")
def flow_status(run_id: str):
    """{state: none | queued | running | ready | failed | stale, progress 0..1, ...summary when ready}."""
    return flow.status(run_id)


@router.post("/api/runs/{run_id}/flow")
def flow_start(run_id: str, force: bool = False, user: dict = Depends(require("viewer"))):
    if not fs.get_doc("runs", run_id):
        raise HTTPException(404, "Unknown run")
    return flow.start(run_id, force)


@router.get("/api/runs/{run_id}/flow/frames.bin")
def flow_frames(run_id: str, model: str = "flow"):
    """uint8 frames [F, 3, rows, cols] (depth code, east and north velocity codes; see engines/swe.encode_frame),
    gzip-encoded. model=flow is the 2D flow model every 5 minutes; model=hand is the map's hourly HAND depth."""
    name = "flow/frames.bin" if model == "flow" else "flow/hand_frames.bin"
    try:
        data = storage.get_run_gz(run_id, name)
    except NotFound:
        if model == "flow":
            raise HTTPException(404, "Flow model not run yet")
        try:
            storage.put_run_gz(run_id, name, flow.hand_frames(run_id))
        except NotFound:
            raise HTTPException(404, "Unknown run")
        data = storage.get_run_gz(run_id, name)
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Encoding": "gzip", "Cache-Control": "public, max-age=86400"})
