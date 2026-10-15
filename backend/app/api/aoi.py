from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.engines.grid import make_grid
from app.engines.render import overlay_payload
from app.models.aoi import AOIRequest, AOIValidationError, build_aoi
from app.pipeline.prepare_area import prepare_area
from app.services import firestore as fs
from app.services import storage

router = APIRouter()


@router.post("/api/aoi")
def create_aoi(req: AOIRequest, background: BackgroundTasks):
    try:
        aoi = build_aoi(req)
    except AOIValidationError as e:
        raise HTTPException(422, str(e))
    existing = fs.get_aoi(aoi.aoi_id)
    if existing and existing.get("state") in ("preparing", "ready"):
        return {"aoi": aoi, "state": existing["state"], "status": existing.get("status", {})}
    fs.set_aoi(aoi.aoi_id, {**aoi.model_dump(mode="json"), "state": "queued", "status": {}})
    background.add_task(prepare_area, aoi)
    return {"aoi": aoi, "state": "queued", "status": {}}


@router.get("/api/aoi/{aoi_id}/status")
def aoi_status(aoi_id: str):
    doc = fs.get_aoi(aoi_id)
    if not doc:
        raise HTTPException(404, "Unknown AOI")
    keys = ("state", "status", "warnings", "meta", "prepare_seconds", "prepared_at")
    return {"aoi_id": aoi_id, **{k: doc.get(k) for k in keys}}


@router.get("/api/aoi/{aoi_id}/static-layers")
def static_layers(aoi_id: str):
    doc = fs.get_aoi(aoi_id)
    if not doc:
        raise HTTPException(404, "Unknown AOI")
    grid = make_grid(tuple(doc["bbox"]))
    layers = {}
    if storage.exists(aoi_id, "png/hand.png"):
        layers["hand"] = f"/api/layers/{aoi_id}/hand.png"
    return {"aoi_id": aoi_id, "layers": layers, **overlay_payload(grid)}
