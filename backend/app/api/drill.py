"""Tabletop drills on a stored run (agents/drill.py): start, answer injects, after-action report."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agents import drill as D
from app.auth import require
from app.services import firestore as fs

router = APIRouter()
COLL = "drills"


class Start(BaseModel):
    participant: str = ""


class Answer(BaseModel):
    index: int = Field(ge=0)
    response: str = Field(min_length=1, max_length=2000)


def _get(drill_id: str) -> dict:
    d = fs.get_doc(COLL, drill_id)
    if not d:
        raise HTTPException(404, "Unknown drill")
    return d


# plain `def` handlers: FastAPI runs them in its threadpool (Gemini and Firestore calls block; on the event loop they
# stalled every other request)
@router.post("/api/runs/{run_id}/drill")
def start_drill(run_id: str, body: Start, user: dict = Depends(require("viewer"))):
    run = fs.get_doc("runs", run_id)
    if not run:
        raise HTTPException(404, "Unknown run")
    d = D.new_drill(run, body.participant or user.get("name") or "")
    fs.set_doc(COLL, d["drill_id"], d)
    return d


@router.get("/api/runs/{run_id}/drills")
def list_drills(run_id: str):
    rows = [x.to_dict() for x in fs.get_db().collection(COLL).where("run_id", "==", run_id).limit(50).stream()]
    keep = ("drill_id", "created_at", "participant", "source")
    out = [{k: r.get(k) for k in keep} | {"answered": len(r.get("responses") or {}), "injects": len(r["plan"]["injects"]),
                                         "score": (r.get("report") or {}).get("score")} for r in rows]
    return sorted(out, key=lambda r: r["created_at"], reverse=True)


@router.get("/api/drills/{drill_id}")
def get_drill(drill_id: str):
    return _get(drill_id)


@router.post("/api/drills/{drill_id}/answer")
def answer(drill_id: str, body: Answer, user: dict = Depends(require("viewer"))):
    d = _get(drill_id)
    if body.index >= len(d["plan"]["injects"]):
        raise HTTPException(400, "No such inject")
    run = fs.get_doc("runs", d["run_id"])
    ev = D.evaluate(d, run, body.index, body.response)
    fs.merge_doc(COLL, drill_id, {"responses": {str(body.index): ev}})
    return ev


@router.post("/api/drills/{drill_id}/report")
def drill_report(drill_id: str, user: dict = Depends(require("viewer"))):
    d = _get(drill_id)
    if not d.get("responses"):
        raise HTTPException(400, "Answer at least one inject first")
    rep = D.report(d)
    fs.merge_doc(COLL, drill_id, {"report": rep})
    return rep
