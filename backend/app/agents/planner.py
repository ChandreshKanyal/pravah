"""S14.3 scenario_planner: an ADK LlmAgent with output_schema turns an official's request into parameter changes.

The API returns the merged params and a diff; the human clicks Apply before anything runs (human in the loop).
"""
import json
import uuid
from typing import Literal

from google.adk.agents import LlmAgent
from google.adk.planners import BuiltInPlanner
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field

import app.agents  # noqa: F401  (Vertex env)
from app.config import get_settings
from app.models.scenario import ScenarioParams


class PlanOverrides(BaseModel):
    """Only the fields the request mentions; everything else stays null."""
    rain_source: Literal["forecast", "worst", "best", "historical_extreme", "manual"] | None = None
    forecast_day_index: int | None = Field(None, description="0..9")
    manual_intensity_mm_h: float | None = Field(None, description="5..150 mm/h; implies rain_source manual")
    duration_h: int | None = Field(None, description="1..24")
    hyetograph: Literal["constant", "triangular_front"] | None = None
    worst_multiplier: float | None = None
    river_offset_m: float | None = Field(None, description="-1..5 m")
    upstream_inflow_m3s: float | None = Field(None, description="river flow entering from upstream, m3/s (0..20000)")
    pop_multiplier: float | None = Field(None, description="0.5..2")
    pop_total_override: int | None = None
    travel_mode: Literal["walk", "drive"] | None = None
    evac_start_hour: int | None = None
    disabled_shelter_ids: list[str] | None = Field(None, description="full list of closed shelter ids after the change")
    bridge_cut_stage_m: float | None = None
    walk_depth_limit_m: float | None = None
    vehicle_depth_limit_m: float | None = None
    max_travel_min: int | None = None
    explanation: str = Field("", description="one short sentence on what was changed and why")


INSTRUCTION = """Convert the official's request into ScenarioParams changes. Only change fields the request mentions.
Map shelter names to ids from the provided list (disabled_shelter_ids must be the complete list of closed shelters,
including ones already closed unless the request reopens them). Keep values within allowed ranges. A rain rate in
mm per hour means rain_source=manual with manual_intensity_mm_h. If the request is ambiguous, keep current values
(leave fields null). Output only the schema."""

RANGES = {"upstream_inflow_m3s": (0, 20000), "manual_intensity_mm_h": (0, 300), "duration_h": (1, 24), "river_offset_m": (-1, 5), "pop_multiplier": (0.5, 2),
          "forecast_day_index": (0, 9), "evac_start_hour": (1, 24), "worst_multiplier": (1, 5)}


def _agent() -> LlmAgent:
    s = get_settings()
    return LlmAgent(name="scenario_planner", model=s.gemini_model_fast, instruction=INSTRUCTION,
                    output_schema=PlanOverrides, output_key="plan",
                    planner=BuiltInPlanner(thinking_config=types.ThinkingConfig(thinking_level=s.gemini_thinking_fast)),
                    generate_content_config=types.GenerateContentConfig(temperature=0.1))


async def plan(text: str, current: ScenarioParams, shelters: list[dict], forecast_days: list[dict] | None = None) -> dict:
    """{params, diff: {field: [old, new]}, explanation}. Nothing is run here."""
    ss = InMemorySessionService()
    sid = uuid.uuid4().hex
    await ss.create_session(app_name="pravah_plan", user_id="planner", session_id=sid)
    ctx = {"request": text, "current_params": current.model_dump(exclude={"blocked_polygons", "extra_shelters"}),
           "shelters": [{"id": s["id"], "name": s["name"], "kind": s.get("kind")} for s in shelters],
           "forecast_days": forecast_days or []}
    msg = types.Content(role="user", parts=[types.Part(text=json.dumps(ctx))])
    runner = Runner(app_name="pravah_plan", agent=_agent(), session_service=ss)
    async for _ in runner.run_async(user_id="planner", session_id=sid, new_message=msg):
        pass
    sess = await ss.get_session(app_name="pravah_plan", user_id="planner", session_id=sid)
    raw = sess.state.get("plan") or {}
    ov = PlanOverrides.model_validate(raw)
    return merge(current, ov, {s["id"] for s in shelters})


def merge(current: ScenarioParams, ov: PlanOverrides, shelter_ids: set[str]) -> dict:
    p = current.model_dump()
    changes = {k: v for k, v in ov.model_dump(exclude={"explanation"}).items() if v is not None}
    if "manual_intensity_mm_h" in changes and "rain_source" not in changes:
        changes["rain_source"] = "manual"
    for k, (lo, hi) in RANGES.items():
        if k in changes:
            changes[k] = type(changes[k])(min(hi, max(lo, changes[k])))
    if "disabled_shelter_ids" in changes:
        changes["disabled_shelter_ids"] = sorted(i for i in changes["disabled_shelter_ids"] if i in shelter_ids)
    p.update(changes)
    new = ScenarioParams(**p)
    diff = {k: [getattr(current, k), getattr(new, k)] for k in changes if getattr(current, k) != getattr(new, k)}
    for k, v in diff.items():
        diff[k] = [x.value if hasattr(x, "value") else x for x in v]
    return {"params": new.model_dump(mode="json"), "diff": diff, "explanation": ov.explanation}
