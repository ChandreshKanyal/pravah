import logging

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.models.run import RunResult
from app.models.scenario import ScenarioParams
from app.pipeline.run_pipeline import AreaNotReady, run_pipeline
from app.services import firestore as fs
from app.services import storage

router = APIRouter()
log = logging.getLogger(__name__)


@router.post("/api/runs", response_model=RunResult)
def create_run(params: ScenarioParams):
    try:
        return run_pipeline(params)
    except AreaNotReady as e:
        raise HTTPException(409, str(e))


@router.get("/api/runs/{run_id}", response_model=RunResult)
def get_run(run_id: str):
    doc = fs.get_doc("runs", run_id)
    if not doc:
        raise HTTPException(404, "Unknown run")
    return doc


def area_extra(aoi_id: str, run_id: str) -> dict:
    """Area-level facts for the advisory: medical, crowding, verification queue, forecast, history (best effort)."""
    out: dict = {}
    for key, name in (("medical", "medical.json"), ("crowding", "crowd_hotspots.json")):
        if storage.exists(aoi_id, name):
            out[key] = storage.get_json(aoi_id, name)
    try:
        import json
        out["verification"] = json.loads(storage.get_run(run_id, "verification.json"))
    except Exception:
        pass
    try:
        from app.pipeline.run_pipeline import area_centroid, load_area
        from app.services.weather import get_provider
        lon, lat = area_centroid(load_area(aoi_id))
        daily = get_provider().daily(lat, lon, 10)
        if daily:
            w = max(daily, key=lambda d: d["precip_mm"])
            out["forecast"] = {"worst_day": w["date"], "max_daily_mm": round(w["precip_mm"], 1),
                               "source": "Google Maps Platform Weather API"}
    except Exception as e:
        log.info("advisory forecast unavailable: %s", e)
    doc = fs.get_doc("history_cache", aoi_id)
    if doc:
        out["history"] = {"gfd_events": len(doc.get("gfd_events", [])), "landslides": len(doc.get("landslides", [])),
                          "agreement_pct": doc.get("agreement_pct")}
    return out


_jobs: dict = {}
_pool = None


def _generate_and_store(run_id: str) -> None:
    from app.agents.advisor import generate_advisory
    try:
        run = fs.get_doc("runs", run_id)
        adv = generate_advisory(run, area_extra(run["aoi_id"], run_id))
        fs.set_doc("advisories", run_id, {**adv.model_dump(mode="json"), "status": "ready"})
        fs.get_db().collection("runs").document(run_id).update({"advisory_id": run_id})
    except Exception as e:
        log.exception("advisory job failed")
        fs.set_doc("advisories", run_id, {"status": "error", "error": str(e)[:300]})
    finally:
        _jobs.pop(run_id, None)


@router.post("/api/runs/{run_id}/advisory")
async def advisory(run_id: str, refresh: bool = False, rules_only: bool = False):
    """S15.5: return the cached advisory, or start generating it in the background and return {status: pending}.
    Gemini with high thinking takes ~50 s, beyond Firebase Hosting's 60 s rewrite budget, so the UI polls GET."""
    global _pool
    run = fs.get_doc("runs", run_id)
    if not run:
        raise HTTPException(404, "Unknown run")
    if rules_only:  # instant deterministic brief (also the forced-fallback test path)
        from app.agents.advisor import generate_advisory
        extra = await run_in_threadpool(area_extra, run["aoi_id"], run_id)
        return (await run_in_threadpool(generate_advisory, run, extra, False)).model_dump(mode="json")
    doc = fs.get_doc("advisories", run_id)
    if doc and doc.get("status", "ready") == "ready" and not refresh:
        return doc
    if run_id not in _jobs:
        from concurrent.futures import ThreadPoolExecutor
        _pool = _pool or ThreadPoolExecutor(4)
        fs.set_doc("advisories", run_id, {"status": "pending"})
        _jobs[run_id] = _pool.submit(_generate_and_store, run_id)
    return {"status": "pending", "run_id": run_id}


@router.get("/api/runs/{run_id}/advisory")
def get_advisory(run_id: str):
    doc = fs.get_doc("advisories", run_id)
    if not doc:
        raise HTTPException(404, "No advisory yet")
    return doc
