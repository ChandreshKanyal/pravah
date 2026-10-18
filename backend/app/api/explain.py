"""Click a shelter or route on the map: the run's facts for it, plus Gemini's plain-words explanation of the choice
(agents/explain.py), cached per run."""
import json
import logging

from fastapi import APIRouter, HTTPException
from google.api_core.exceptions import NotFound

from app.agents import explain as ex
from app.services import firestore as fs
from app.services import storage

log = logging.getLogger(__name__)
router = APIRouter()


def _route(run_id: str, run: dict, key: str) -> dict | None:
    """A route by "<from_node>-<to_shelter>": the run's top routes first, else its full routes file."""
    node, _, sid = key.partition("-")
    match = lambda r: str(r.get("from_node")) == node and r.get("to_shelter") == sid  # noqa: E731
    r = next((x for x in run.get("routes", []) if match(x)), None)
    if r is None:
        try:
            fc = json.loads(storage.get_run(run_id, "routes.geojson"))
            r = next((f["properties"] for f in fc.get("features", []) if match(f["properties"])), None)
        except NotFound:
            pass
    return r


@router.get("/api/runs/{run_id}/explain/{kind}/{key}")
def explain(run_id: str, kind: str, key: str):
    """{facts, ai: {headline, reasons, cautions} | null}. kind: shelter (key = shelter id) | route (key = from_node-to_shelter)."""
    if kind not in ("shelter", "route"):
        raise HTTPException(404, "Unknown kind")
    cache = f"explain/{kind}_{key}.json"
    try:
        return json.loads(storage.get_run(run_id, cache))
    except NotFound:
        pass
    run = fs.get_doc("runs", run_id)
    if not run:
        raise HTTPException(404, "Unknown run")
    if kind == "shelter":
        facts = ex.shelter_facts(run, key)
    else:
        r = _route(run_id, run, key)
        facts = ex.route_facts(run, r) if r else None
    if facts is None:
        raise HTTPException(404, f"No {kind} {key} in this run")
    try:
        ai = ex.explain(kind, facts)
    except Exception as e:  # the facts still show; the explanation can be asked for again
        log.warning("explain %s %s/%s failed: %s", run_id, kind, key, e)
        return {"facts": facts, "ai": None}
    out = {"facts": facts, "ai": ai}
    storage.put_run(run_id, cache, json.dumps(out, default=str).encode(), "application/json")
    return out
