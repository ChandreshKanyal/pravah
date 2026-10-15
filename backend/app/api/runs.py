from fastapi import APIRouter, HTTPException

from app.models.run import RunResult
from app.models.scenario import ScenarioParams
from app.pipeline.run_pipeline import AreaNotReady, run_pipeline
from app.services import firestore as fs

router = APIRouter()


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
