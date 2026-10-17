from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from google.api_core.exceptions import NotFound
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
    if existing and existing.get("mode"):  # an area prepared before keeps its terrain family (cached layers)
        aoi = aoi.model_copy(update={"mode": existing["mode"]})
    from app.pipeline.prepare_area import ACTIVE
    interrupted = existing and existing.get("state") in ("preparing", "queued") and aoi.aoi_id not in ACTIVE
    if existing and existing.get("state") in ("preparing", "ready") and not interrupted:
        return {"aoi": aoi, "state": existing["state"], "status": existing.get("status", {})}
    if interrupted:  # e.g. the server restarted mid-way: resume (finished steps are skipped)
        fs.update_aoi(aoi.aoi_id, {"state": "queued"})
        background.add_task(prepare_area, aoi)
        return {"aoi": aoi, "state": "queued", "status": existing.get("status", {})}
    fs.set_aoi(aoi.aoi_id, {**aoi.model_dump(mode="json"), "state": "queued", "status": {}})
    background.add_task(prepare_area, aoi)
    return {"aoi": aoi, "state": "queued", "status": {}}


@router.get("/api/aoi/{aoi_id}/status")
def aoi_status(aoi_id: str):
    doc = fs.get_aoi(aoi_id)
    if not doc:
        raise HTTPException(404, "Unknown AOI")
    keys = ("state", "status", "warnings", "meta", "prepare_seconds", "prepared_at", "name", "bbox", "mode", "latest_run_id",
            "official", "archived", "drain")
    return {"aoi_id": aoi_id, **{k: doc.get(k) for k in keys}}


def _json_or(aoi_id: str, name: str, default):
    try:
        return storage.get_json(aoi_id, name)
    except NotFound:
        return default


@router.get("/api/aoi/{aoi_id}/static-layers")
def static_layers(aoi_id: str):
    """Opened with every area: the storage reads run in parallel (12 one after another took ~1 s)."""
    doc = fs.get_aoi(aoi_id)
    if not doc:
        raise HTTPException(404, "Unknown AOI")
    grid = make_grid(tuple(doc["bbox"]))
    pngs, keys = ("hand", "streams", "fsi", "crowd"), ("hotspots", "shelters", "medical", "crowd_hotspots")
    with ThreadPoolExecutor(8) as ex:
        has = list(ex.map(lambda n: storage.exists(aoi_id, f"png/{n}.png"), pngs))
        js = dict(zip(keys, ex.map(lambda k: _json_or(aoi_id, f"{k}.json", []), keys)))
    layers = {n: f"/api/layers/{aoi_id}/{n}.png" for n, ok in zip(pngs, has) if ok}
    return {"aoi_id": aoi_id, "layers": layers, **js, **overlay_payload(grid)}


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
    keep = ["aoi_id", "name", "bbox", "mode", "state", "prepared_at", "latest_run_id"]
    docs = fs.get_db().collection("aois").select(keep + ["archived"]).limit(200).stream()  # the listed fields only
    rows = [fs.decode(d.to_dict()) for d in docs]
    rows = [{k: r.get(k) for k in keep} for r in rows if r.get("bbox") and not r.get("archived")]
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


def _runs(aoi_id: str) -> list[dict]:
    return [fs.decode(d.to_dict()) for d in fs.get_db().collection("runs").where("aoi_id", "==", aoi_id).limit(300).stream()]


_META = ("run_id", "created_at", "title", "notes", "starred", "archived")
_summary: dict[str, dict] = {}  # run_id -> summary of the immutable result fields (runs never change after they finish)


def _summarise(r: dict) -> dict:
    keep = ("rain_label", "people_to_evacuate", "capacity_gap_people", "demand_range", "gap_range", "evac_window_h", "start_local")
    row = {k: r.get(k) for k in keep}
    b = r.get("bridges") or []
    row["bridges_closing"] = sum(1 for x in b if x.get("first_closed_hour"))
    row["bridges_total"] = len(b)
    row["flooded_km2"] = (r.get("flooded_area_km2_by_hour") or [0])[-1]
    e = r.get("exposure") or {}
    row["flood_peak"] = max(e.get("exposed_pop_by_hour") or [0])
    row["shelters_used"] = sum(1 for s in r.get("shelters") or [] if s.get("assigned", 0) > 0)
    p = r.get("params") or {}
    ch = {k: p.get(k) for k in ("disabled_shelter_ids", "visitors", "travel_mode", "evac_start_hour") if p.get(k)}
    ch["extra_shelters"] = len(p.get("extra_shelters") or []) or None
    ch["blocked_polygons"] = len(p.get("blocked_polygons") or []) or None
    row["changes"] = {k: v for k, v in ch.items() if v}
    row["duration_h"], row["rain_total_mm"] = int(p.get("duration_h") or 0), round(sum(r.get("rain_series_mm_h") or []), 1)
    row["rain_source"], row["rain_preset"], row["river_offset_m"] = p.get("rain_source"), p.get("rain_preset"), p.get("river_offset_m")
    return row


def run_summaries(aoi_id: str) -> list[dict]:
    """Summary rows of an area's runs. Lists only the small editable fields from Firestore (field projection) and
    reads a full run document once, the first time it is seen: listing used to download every run in full (5-13 s)."""
    db = fs.get_db()
    docs = db.collection("runs").where("aoi_id", "==", aoi_id).select(list(_META)).limit(300).stream()
    metas = [d.to_dict() | {"run_id": d.to_dict().get("run_id") or d.id} for d in docs]
    missing = [m["run_id"] for m in metas if m["run_id"] not in _summary]
    if missing:  # one batched read for the runs not seen yet (they used to be read one at a time)
        for snap in db.get_all([db.collection("runs").document(r) for r in missing]):
            _summary[snap.id] = _summarise(fs.decode(snap.to_dict()) if snap.exists else {})
        for r in missing:
            _summary.setdefault(r, _summarise({}))
    return [{**_summary[m["run_id"]], **{k: m.get(k) for k in _META}} for m in metas]


@router.delete("/api/aoi/{aoi_id}")
def delete_aoi(aoi_id: str, user: dict = Depends(require("analyst"))):
    """Permanently delete an area with all its runs and prepared data."""
    if not fs.get_aoi(aoi_id):
        raise HTTPException(404, "Unknown AOI")
    from app.api.runs import audit
    from app.pipeline import cleanup
    from app.pipeline.prepare_area import ACTIVE
    if aoi_id in ACTIVE:
        raise HTTPException(409, "This area is still being prepared; delete it when preparation finishes")
    res = cleanup.delete_area(aoi_id)
    audit("delete_area", user, aoi_id=aoi_id, runs=res["runs"])
    return res


@router.get("/api/aoi/{aoi_id}/runs")
def aoi_runs(aoi_id: str, limit: int = Query(10, ge=1, le=100), archived: bool = False):
    """Saved scenarios (experiments) of an area, newest first, summary fields only. Archived runs only on request."""
    rows = []
    current = (fs.get_aoi(aoi_id) or {}).get("latest_run_id")
    for row in run_summaries(aoi_id):
        if bool(row.get("archived")) != archived:
            continue
        row["is_current"] = row["run_id"] == current
        rows.append(row)
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows[:limit]


@router.get("/api/projects")
def projects():
    """Projects page: every prepared area with its saved runs counted (archived areas listed separately)."""
    out = []
    db = fs.get_db()
    keep = ["aoi_id", "name", "bbox", "mode", "state", "prepared_at", "latest_run_id", "archived"]
    by_area: dict[str, list] = {}
    for r in db.collection("runs").select(["aoi_id", "created_at", "starred", "archived"]).stream():  # one query, not one per area
        x = r.to_dict()
        if not x.get("archived"):  # counts only: the small fields, not whole run documents
            by_area.setdefault(x.get("aoi_id"), []).append(x)
    for d in db.collection("aois").select(keep).limit(200).stream():
        a = fs.decode(d.to_dict())
        if not a.get("bbox"):
            continue
        runs = by_area.get(a.get("aoi_id"), [])[:300]
        last = max((str(r.get("created_at") or "") for r in runs), default="")
        out.append({k: a.get(k) for k in ("aoi_id", "name", "bbox", "mode", "state", "prepared_at", "latest_run_id", "archived")} |
                   {"runs": len(runs), "starred": sum(1 for r in runs if r.get("starred")), "last_run_at": last or None})
    out.sort(key=lambda r: str(r.get("last_run_at") or r.get("prepared_at") or ""), reverse=True)
    out.sort(key=lambda r: bool(r.get("archived")))
    return out


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


class DrainChoice(BaseModel):
    mm_h: float | None  # None goes back to the default
    city: str = ""
    basis: str = ""
    sources: list[dict] = []


@router.post("/api/aoi/{aoi_id}/drain/lookup")
def drain_lookup(aoi_id: str, user: dict = Depends(require("analyst"))):
    """Gemini with Google Search: the city's storm-drain design capacity with sources. Nothing is saved."""
    if not fs.get_aoi(aoi_id):
        raise HTTPException(404, "Unknown AOI")
    from app.agents.drain_lookup import lookup
    return lookup(aoi_id)


@router.post("/api/aoi/{aoi_id}/drain")
def drain_set(aoi_id: str, body: DrainChoice, user: dict = Depends(require("analyst"))):
    """A person confirms the storm-drain capacity for this area (from the lookup, or their own figure); new runs use it."""
    if not fs.get_aoi(aoi_id):
        raise HTTPException(404, "Unknown AOI")
    if body.mm_h is not None and not 5 <= body.mm_h <= 150:
        raise HTTPException(422, "Drain capacity must be between 5 and 150 mm/h")
    val = None if body.mm_h is None else {"mm_h": body.mm_h, "city": body.city, "basis": body.basis,
                                          "sources": body.sources[:6], "confirmed_by": user.get("email", "local"),
                                          "at": datetime.now(timezone.utc).isoformat()}
    fs.update_aoi(aoi_id, {"drain": val})
    return {"drain": val}
