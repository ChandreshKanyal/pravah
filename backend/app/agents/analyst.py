"""S14.4/S14.6 analyst: an ADK LlmAgent with the S14.2 tools, one in-memory session per browser tab."""
import logging

from google.adk.agents import LlmAgent
from google.adk.planners import BuiltInPlanner
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

import app.agents  # noqa: F401  (Vertex env)
from app.agents.tools import TOOLS
from app.config import get_settings

log = logging.getLogger(__name__)
APP = "pravah"

INSTRUCTION = """You help district officials explore flood and landslide scenarios for one area (aoi {aoi_id}); the
current run is {run_id?}. Never state a number you did not get from a tool result. For what-if questions, call
run_scenario with only the changed fields, then compare_runs against the previous run. To close a shelter by name,
call find_shelter_by_name first. For a quick "what if X mm in Y hours" use instant_what_if (seconds, flood and
people only) and offer run_scenario for routes and shelters; for "how much rain floods <place>" use rain_triggers. Cite ids (shelters S..., assembly points A..., bridges B..., clusters C...). Use the
words estimated, susceptibility, suggested; never say "will flood" or "safe" (say "reachable in this scenario").
Building classes are proxies ("likely kaccha"). Keep answers short: a sentence or two, then a few bullets. End
substantive answers with: "Decision-support draft for official review." """

_sessions = InMemorySessionService()
_runner: Runner | None = None


def _get_runner() -> Runner:
    global _runner
    if _runner is None:
        s = get_settings()
        agent = LlmAgent(name="analyst", model=s.gemini_model_fast, instruction=INSTRUCTION, tools=TOOLS,
                         planner=BuiltInPlanner(thinking_config=types.ThinkingConfig(thinking_level=s.gemini_thinking_fast)),
                         generate_content_config=types.GenerateContentConfig(temperature=0.2))
        _runner = Runner(app_name=APP, agent=agent, session_service=_sessions)
    return _runner


async def chat(session_id: str, aoi_id: str, run_id: str | None, message: str) -> dict:
    """{reply, new_run_id?, tools_called}. The UI's current run overrides the session's, so both stay in sync."""
    user = "official"
    sess = await _sessions.get_session(app_name=APP, user_id=user, session_id=session_id)
    if sess is None:
        await _sessions.create_session(app_name=APP, user_id=user, session_id=session_id,
                                       state={"aoi_id": aoi_id, "run_id": run_id})
    delta = {"aoi_id": aoi_id, "new_run_id": None}
    if run_id:
        delta["run_id"] = run_id
    msg = types.Content(role="user", parts=[types.Part(text=message)])
    texts, calls = [], []
    async for ev in _get_runner().run_async(user_id=user, session_id=session_id, new_message=msg, state_delta=delta):
        for p in (ev.content.parts if ev.content and ev.content.parts else []):
            if p.function_call:
                calls.append(p.function_call.name)
            elif p.text and not getattr(p, "thought", False) and ev.author == "analyst":
                texts.append(p.text)
    sess = await _sessions.get_session(app_name=APP, user_id=user, session_id=session_id)
    reply = (texts[-1] if texts else "").strip() or "Sorry, I could not produce an answer. Please try rephrasing."
    return {"reply": reply, "new_run_id": sess.state.get("new_run_id"), "tools_called": calls}
