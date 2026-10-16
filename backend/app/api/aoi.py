from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from app.auth import require

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
def create_aoi(req: AOIRequest, background: BackgroundTasks, user: dict = Depends(require("analyst"))):
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
    keys = ("state", "status", "warnings", "meta", "prepare_seconds", "prepared_at", "name", "bbox", "mode", "latest_run_id",
            "official", "archived")
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
            if r.get("bbox") and not r.get("archived")]
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


class Archive(BaseModel):
    archived: bool = True


@router.post("/api/aoi/{aoi_id}/archive")
def archive_aoi(aoi_id: str, body: Archive, user: dict = Depends(require("analyst"))):
    """Hide an area from the Explore list (data is kept; reversible)."""
    if not fs.get_aoi(aoi_id):
        raise HTTPException(404, "Unknown AOI")
    fs.update_aoi(aoi_id, {"archived": body.archived})
    from app.api.runs import audit
    audit("archive" if body.archived else "unarchive", user, aoi_id=aoi_id)
    return {"aoi_id": aoi_id, "archived": body.archived}


@router.get("/api/aoi/{aoi_id}/runs")
def aoi_runs(aoi_id: str, limit: int = Query(10, ge=1, le=30)):
    """Recent scenarios for side-by-side comparison (summary fields only)."""
    docs = fs.get_db().collection("runs").where("aoi_id", "==", aoi_id).limit(200).stream()
    keep = ("run_id", "created_at", "rain_label", "people_to_evacuate", "capacity_gap_people", "demand_range", "gap_range",
            "evac_window_h", "start_local", "params")
    rows = []
    for d in docs:
        r = d.to_dict()
        row = {k: r.get(k) for k in keep}
        b = r.get("bridges") or []
        row["bridges_closing"] = sum(1 for x in b if x.get("first_closed_hour"))
        row["bridges_total"] = len(b)
        row["flooded_km2"] = (r.get("flooded_area_km2_by_hour") or [0])[-1]
        e = r.get("exposure") or {}
        row["flood_peak"] = max(e.get("exposed_pop_by_hour") or [0])
        row["shelters_used"] = sum(1 for s in r.get("shelters") or [] if s.get("assigned", 0) > 0)
        p = row.pop("params") or {}
        row["changes"] = {k: p.get(k) for k in ("disabled_shelter_ids", "extra_shelters", "blocked_polygons", "visitors",
                                                "travel_mode", "evac_start_hour") if p.get(k)}
        row["changes"]["extra_shelters"] = len(p.get("extra_shelters") or []) or None
        row["changes"]["blocked_polygons"] = len(p.get("blocked_polygons") or []) or None
        row["changes"] = {k: v for k, v in row["changes"].items() if v}
        rows.append(row)
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows[:limit]


class Official(BaseModel):
    imd_warning: str | None = None  # green | yellow | orange | red (IMD district colour code, as issued)
    imd_valid_for: str = ""  # e.g. "17 Oct, district warning"
    cwc_station: str = ""
    cwc_level_m: float | None = None
    cwc_warning_m: float | None = None
    cwc_danger_m: float | None = None
    cwc_hfl_m: float | None = None  # highest flood level on record
    note: str = ""


@router.put("/api/aoi/{aoi_id}/official")
def set_official(aoi_id: str, body: Official, user: dict = Depends(require("analyst"))):
    """Official warnings typed in by staff (IMD colour code, CWC gauge levels): shown next to the model so the brief
    can be read against them. Pravah does not scrape IMD or CWC; the source links are on the page."""
    if body.imd_warning not in (None, "green", "yellow", "orange", "red"):
        raise HTTPException(422, "IMD warning must be green, yellow, orange or red")
    if not fs.get_aoi(aoi_id):
        raise HTTPException(404, "Unknown AOI")
    doc = {**body.model_dump(), "entered_by": user.get("name") or "unverified user", "verified": bool(user.get("verified")),
           "at": datetime.now(timezone.utc).isoformat()}
    fs.update_aoi(aoi_id, {"official": doc})
    from app.api.runs import audit
    audit("official_status", user, aoi_id=aoi_id, imd=body.imd_warning, cwc_level=body.cwc_level_m)
    return doc
