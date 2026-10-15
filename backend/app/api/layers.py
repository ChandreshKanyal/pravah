import re

from fastapi import APIRouter, HTTPException, Response
from google.api_core.exceptions import NotFound

from app.services import storage

router = APIRouter()
_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")


@router.get("/api/layers/{aoi_id}/{name}.png")
def layer_png(aoi_id: str, name: str):
    if not (_SAFE.match(aoi_id) and _SAFE.match(name)):
        raise HTTPException(400, "Bad layer name")
    try:
        data = storage.get_bytes(aoi_id, f"png/{name}.png")
    except NotFound:
        raise HTTPException(404, "Layer not found")
    return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/api/runs/{run_id}/layers/{name}.png")
def run_layer_png(run_id: str, name: str):
    if not (_SAFE.match(run_id) and _SAFE.match(name)):
        raise HTTPException(400, "Bad layer name")
    try:
        data = storage.get_run(run_id, f"png/{name}.png")
    except NotFound:
        raise HTTPException(404, "Layer not found")
    return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
