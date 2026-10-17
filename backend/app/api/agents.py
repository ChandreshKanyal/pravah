"""S14 endpoints: /api/plan (language -> params diff, nothing runs) and /api/chat (analyst with tools)."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import require
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
async def plan(req: PlanRequest, user: dict = Depends(require("analyst"))):
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
async def chat(req: ChatRequest, user: dict = Depends(require("analyst"))):
    from app.agents.analyst import chat as run_chat
    try:
        return await run_chat(req.session_id[:64], req.aoi_id, req.run_id, req.message[:2000])
    except Exception as e:
        log.exception("chat failed")
        raise HTTPException(502, f"Assistant unavailable ({e.__class__.__name__})")


class AssistantRequest(BaseModel):
    session_id: str
    message: str
    page: str = ""
    aoi_id: str | None = None
    run_id: str | None = None


@router.post("/api/assistant")
async def assistant(req: AssistantRequest, user: dict = Depends(require("analyst"))):
    """The floating assistant on every page: answers (web-grounded), finds places, and proposes actions to confirm."""
    from app.agents.assistant import ask
    try:
        return await ask(req.session_id[:64], req.message[:2000], req.page[:40], req.aoi_id, req.run_id)
    except Exception as e:
        log.exception("assistant failed")
        raise HTTPException(502, f"Assistant unavailable ({e.__class__.__name__})")


@router.post("/api/assistant/stream")
async def assistant_stream(req: AssistantRequest, user: dict = Depends(require("analyst"))):
    """Server-sent events for the chat: steps, thinking summaries and answer text as they happen, then the result."""
    import json as _json

    from fastapi.responses import StreamingResponse

    from app.agents.assistant import ask_stream

    async def gen():
        try:
            async for e in ask_stream(req.session_id[:64], req.message[:2000], req.page[:40], req.aoi_id, req.run_id):
                yield f"data: {_json.dumps(e)}\n\n"
        except Exception as e:  # noqa: BLE001
            log.exception("assistant stream failed")
            yield f"data: {_json.dumps({'type': 'error', 'message': f'Assistant unavailable ({e.__class__.__name__})'})}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
