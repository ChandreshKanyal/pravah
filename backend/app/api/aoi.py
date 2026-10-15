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
    keys = ("state", "status", "warnings", "meta", "prepare_seconds", "prepared_at", "name", "bbox", "mode", "latest_run_id")
    return {"aoi_id": aoi_id, **{k: doc.get(k) for k in keys}}


@router.get("/api/aoi/{aoi_id}/static-layers")
def static_layers(aoi_id: str):
    doc = fs.get_aoi(aoi_id)
    if not doc:
        raise HTTPException(404, "Unknown AOI")
    grid = make_grid(tuple(doc["bbox"]))
    layers = {n: f"/api/layers/{aoi_id}/{n}.png" for n in ("hand", "streams", "fsi", "lsi_static", "crowd") if storage.exists(aoi_id, f"png/{n}.png")}
    hotspots = storage.get_json(aoi_id, "hotspots.json") if storage.exists(aoi_id, "hotspots.json") else []
    extra = {k: storage.get_json(aoi_id, f"{k}.json") if storage.exists(aoi_id, f"{k}.json") else []
             for k in ("shelters", "medical", "crowd_hotspots")}
    return {"aoi_id": aoi_id, "layers": layers, "hotspots": hotspots, **extra, **overlay_payload(grid)}


@router.get("/api/aoi/{aoi_id}/flood.png")
def flood_at_stage(aoi_id: str, stage: float = Query(2.0, ge=0, le=30)):
    """S3.1 (M1, temporary): uniform stage above drainage -> HAND flood depth overlay."""
    try:
        area = load_area(aoi_id)
    except AreaNotReady as e:
        raise HTTPException(409, str(e))
    depth = depth_from_stage(area.hand, stage, area.perm)
    return Response(to_png_binned(depth, DEPTH_EDGES, DEPTH_COLORS, nan_color=WATER_COLOR), media_type="image/png")


@router.get("/api/aoi/{aoi_id}/verification-queue")
def verification_queue(aoi_id: str):
    """Buildings ranked for field inspection (S6.9), from the AOI's latest run."""
    doc = fs.get_aoi(aoi_id)
    if not doc:
        raise HTTPException(404, "Unknown AOI")
    run_id = doc.get("latest_run_id")
    if not run_id:
        return {"aoi_id": aoi_id, "run_id": None, "queue": []}
    import json
    return {"aoi_id": aoi_id, "run_id": run_id, "queue": json.loads(storage.get_run(run_id, "verification.json"))}


@router.get("/api/aois")
def list_aois(limit: int = Query(12, ge=1, le=50)):
    """Recently prepared areas for the Explore page (name, bbox, state)."""
    docs = fs.get_db().collection("aois").limit(200).stream()
    rows = [d.to_dict() for d in docs]
    rows = [{k: r.get(k) for k in ("aoi_id", "name", "bbox", "mode", "state", "prepared_at", "latest_run_id")} for r in rows
            if r.get("bbox")]
    rows.sort(key=lambda r: str(r.get("prepared_at") or ""), reverse=True)
    return rows[:limit]


@router.get("/api/geocode")
def geocode(q: str = Query(..., min_length=2, max_length=200)):
    """Search box (Maps Geocoding API, display/navigation only; never stored or used as analysis input)."""
    import requests
    from app.services.weather import maps_server_key
    r = requests.get("https://maps.googleapis.com/maps/api/geocode/json", timeout=10,
                     params={"address": q, "region": "in", "key": maps_server_key()})
    out = []
    for res in (r.json().get("results") or [])[:5]:
        g = res["geometry"]
        vp = g.get("viewport", {})
        out.append({"label": res.get("formatted_address", ""), "lat": g["location"]["lat"], "lng": g["location"]["lng"],
                    "viewport": [vp.get("southwest", {}).get("lng"), vp.get("southwest", {}).get("lat"),
                                 vp.get("northeast", {}).get("lng"), vp.get("northeast", {}).get("lat")] if vp else None})
    return out
