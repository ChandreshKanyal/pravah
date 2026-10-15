from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response

from app.engines.grid import make_grid
from app.engines.flood import depth_from_stage
from app.engines.render import DEPTH_COLORS, DEPTH_EDGES, WATER_COLOR, overlay_payload, to_png_binned
from app.models.aoi import AOIRequest, AOIValidationError, build_aoi
from app.pipeline.prepare_area import prepare_area
from app.pipeline.run_pipeline import AreaNotReady, load_area
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
    layers = {n: f"/api/layers/{aoi_id}/{n}.png" for n in ("hand", "streams") if storage.exists(aoi_id, f"png/{n}.png")}
    hotspots = storage.get_json(aoi_id, "hotspots.json") if storage.exists(aoi_id, "hotspots.json") else []
    return {"aoi_id": aoi_id, "layers": layers, "hotspots": hotspots, **overlay_payload(grid)}


@router.get("/api/aoi/{aoi_id}/flood.png")
def flood_at_stage(aoi_id: str, stage: float = Query(2.0, ge=0, le=30)):
    """S3.1 (M1, temporary): uniform stage above drainage -> HAND flood depth overlay."""
    try:
        area = load_area(aoi_id)
    except AreaNotReady as e:
        raise HTTPException(409, str(e))
    depth = depth_from_stage(area.hand, stage, area.perm)
    return Response(to_png_binned(depth, DEPTH_EDGES, DEPTH_COLORS, nan_color=WATER_COLOR), media_type="image/png")
