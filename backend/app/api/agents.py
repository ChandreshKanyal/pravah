"""S14 endpoints: /api/plan (language -> params diff, nothing runs) and /api/chat (analyst with tools)."""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.scenario import ScenarioParams
from app.services import storage

router = APIRouter()
log = logging.getLogger(__name__)


class PlanRequest(BaseModel):
    aoi_id: str
    text: str
    current_params: ScenarioParams | None = None


class ChatRequest(BaseModel):
    session_id: str
    aoi_id: str
    run_id: str | None = None
    message: str


@router.post("/api/plan")
async def plan(req: PlanRequest):
    from app.agents.planner import plan as run_plan
    if not storage.exists(req.aoi_id, "shelters.json"):
        raise HTTPException(409, "Area not prepared yet")
    current = req.current_params or ScenarioParams(aoi_id=req.aoi_id)
    try:
        return await run_plan(req.text[:2000], current, storage.get_json(req.aoi_id, "shelters.json"))
    except Exception as e:
        log.exception("plan failed")
        raise HTTPException(502, f"Planner unavailable ({e.__class__.__name__}); set the controls by hand")


@router.post("/api/chat")
async def chat(req: ChatRequest):
    from app.agents.analyst import chat as run_chat
    try:
        return await run_chat(req.session_id[:64], req.aoi_id, req.run_id, req.message[:2000])
    except Exception as e:
        log.exception("chat failed")
        raise HTTPException(502, f"Assistant unavailable ({e.__class__.__name__})")
