"""Pravah assistant: one Gemini agent for every page (the floating chat). It answers general questions with Google
Search grounding (sources returned), finds places, knows the user's areas, uses the analysis tools when an area is
open, and drives the platform through *proposed* actions that the user confirms in the UI (navigate, prepare an area,
run a scenario, switch layers). Nothing that moves, runs, costs or deletes happens without that click.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from google.adk.agents import LlmAgent
from google.adk.planners import BuiltInPlanner
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext
from google.genai import types

import app.agents  # noqa: F401  (Vertex env)
from app.agents import tools as T
from app.config import get_settings

log = logging.getLogger(__name__)
APP = "pravah_assistant"

INSTRUCTION = """You are Pravah's assistant, inside a flood and landslide decision-support tool for Indian district
officials. Current page: {page?}. Open area: {aoi_id?} ({aoi_name?}); run on the map: {run_id?}.

How to work:
- General facts (flood-prone places, past floods, rainfall, agencies): call search_web and answer only from its result;
  name places specifically and say they are reported, not predicted. Never invent places or numbers.
- To take the user somewhere or do something in the app, call propose_action; the user confirms it with a button.
  Never claim you did it. Before proposing to move the map, call find_place to get coordinates. Prepare a new area only
  when the user asks to analyse a place; use a box of about 3-10 km around it (urban mode for city drainage, river
  mode for river valleys and hills) and say it takes a few minutes.
- When several places fit (e.g. "flood-prone areas in Mumbai"), list 3-6 with one line each from search_web, then ask
  which one to go to and propose go_to_place for the one the user picks (or the first if they say "take me there").
- With an area open: answer from the analysis tools (get_run_summary, list_bridges, list_shelters, list_closed_roads,
  instant_what_if, rain_triggers, get_forecast_summary, compare_runs). Never state a number you did not get from a
  tool. To run a full scenario, propose run_scenario with only the changed settings.
- If no area is open and the user asks about results, call list_my_areas and offer to open one.
Words: estimated, susceptibility, suggested; never "will flood" or "safe". Be brief: one or two sentences, then a few
bullets. End answers about risk or actions with: "Decision-support draft for official review." """

ACTION_KINDS = {
    "go_to_place": "move the map to a place: args {lat, lng, zoom, label} (zoom 11-16)",
    "open_area": "open a prepared area: args {aoi_id, view} with view one of map, brief, 3d, drill, field, projects",
    "prepare_area": "prepare a new area for analysis: args {name, west, south, east, north, mode} (mode river|urban)",
    "run_scenario": "run a scenario in the open area: args are only the changed settings: rain_source "
                    "(forecast|worst|best|historical_extreme|observed|manual), forecast_day_index (0-9), "
                    "worst_multiplier, duration_h (1-24), river_offset_m (-1..5), manual_intensity_mm_h (with manual), "
                    "hyetograph (constant|triangular_front), or an IMD preset as {rain_source: manual, rain_preset: "
                    "imd_heavy|imd_very_heavy|imd_extreme|cloudburst}",
    "set_layers": "switch map layers: args {on: [...], off: [...]} from depth, roads, routes, shelters, all_shelters, "
                  "bridges, assembly, staging, medical, streams, hand, fsi, lsi, lsi_static, crowd, traffic, history, "
                  "or {fixes: true} to open 'Fix before the rain'",
    "open_page": "open a page: args {page} with page one of projects, methods, home",
}

SEARCH_PROMPT = """Answer this for an Indian district disaster-management official, using web search (not memory):
{place}
Be specific (name places, dates, sources). Reply in under 150 words."""


def search_web(tool_context: ToolContext, query: str) -> dict:
    """Search the web with Google Search (Gemini grounding) for general facts: flood-prone areas, past floods, agencies.

    Args:
        query: the question, e.g. "chronic flooding spots in Mumbai".

    Returns:
        answer (text from the search) and sources (title, uri). Use only these facts.
    """
    from app.agents import historian
    with ThreadPoolExecutor(max_workers=1) as ex:  # the search agent runs its own event loop
        text, entry, sources = ex.submit(historian.search, query, "", SEARCH_PROMPT).result(timeout=90)
    srcs = [s for s in sources if s.get("uri")][:6]
    prev = tool_context.state.get("sources") or []
    tool_context.state["sources"] = (prev + srcs)[:8]
    if entry:
        tool_context.state["search_entry_point"] = entry
    return {"answer": text.strip()[:2500], "sources": [s.get("title", "") for s in srcs]}


def find_place(tool_context: ToolContext, query: str) -> dict:
    """Find a place's coordinates with Google geocoding (display and navigation only).

    Args:
        query: place name, e.g. "Kurla, Mumbai" or "Rudraprayag".

    Returns:
        up to 3 matches with label, lat, lng and viewport [west, south, east, north].
    """
    from app.api.aoi import geocode
    return {"matches": geocode(query)[:3]}


def list_my_areas(tool_context: ToolContext) -> dict:
    """The areas the user has prepared, with run counts (most recent first).

    Returns:
        areas: aoi_id, name, mode, runs, latest_run_id, archived.
    """
    from app.api.aoi import projects
    return {"areas": [{k: a.get(k) for k in ("aoi_id", "name", "mode", "runs", "latest_run_id", "archived")}
                      for a in projects()[:30]]}


def propose_action(tool_context: ToolContext, kind: str, label: str, args_json: str) -> dict:
    """Propose an action in the app; the user sees a button and confirms it. Nothing happens until then.

    Args:
        kind: go_to_place | open_area | prepare_area | run_scenario | set_layers | open_page.
        label: short button text, e.g. "Go to Kurla, Mumbai" or "Run IMD very heavy, 6 h".
        args_json: JSON object with the action's arguments (see the kind list in your instructions).

    Returns:
        proposed: true, or an error to fix.
    """
    if kind not in ACTION_KINDS:
        return {"error": f"unknown kind; use one of {list(ACTION_KINDS)}"}
    try:
        args = json.loads(args_json or "{}")
        assert isinstance(args, dict)
    except Exception:
        return {"error": "args_json must be a JSON object"}
    if kind in ("run_scenario", "set_layers") and not tool_context.state.get("aoi_id"):
        return {"error": "no area is open: propose open_area first"}
    if kind == "run_scenario":
        from app.models.scenario import ScenarioParams
        allowed = set(ScenarioParams.model_fields) - {"aoi_id"}
        bad = [k for k in args if k not in allowed]
        if bad:
            return {"error": f"unknown settings {bad}"}
        if args.get("rain_preset"):
            args["rain_source"] = "manual"
        try:
            ScenarioParams(aoi_id=tool_context.state["aoi_id"], **args)
        except Exception as e:
            return {"error": f"invalid settings: {str(e)[:300]}"}
    props = list(tool_context.state.get("proposals") or [])
    props.append({"kind": kind, "label": label[:80], "args": args})
    tool_context.state["proposals"] = props[-4:]
    return {"proposed": True, "note": "the user must confirm; do not say it is done"}


AREA_TOOLS = [T.get_forecast_summary, T.get_run_summary, T.compare_runs, T.list_shelters, T.list_bridges,
              T.list_closed_roads, T.find_shelter_by_name, T.get_historical_summary, T.instant_what_if, T.rain_triggers]

_sessions = InMemorySessionService()
_runner: Runner | None = None


def _get_runner() -> Runner:
    global _runner
    if _runner is None:
        s = get_settings()
        kinds = "\n".join(f"  - {k}: {v}" for k, v in ACTION_KINDS.items())
        agent = LlmAgent(name="assistant", model=s.gemini_model_fast, instruction=INSTRUCTION + "\nAction kinds:\n" + kinds,
                         tools=[search_web, find_place, list_my_areas, propose_action, *AREA_TOOLS],
                         planner=BuiltInPlanner(thinking_config=types.ThinkingConfig(thinking_level=s.gemini_thinking_fast,
                                                                                     include_thoughts=True)),
                         generate_content_config=types.GenerateContentConfig(temperature=0.2))
        _runner = Runner(app_name=APP, agent=agent, session_service=_sessions)
    return _runner


STEP = {  # what the chat shows while a tool runs (Gemini-style "thinking" steps)
    "search_web": lambda a: f"Searching the web: {a.get('query', '')}",
    "find_place": lambda a: f"Finding {a.get('query', 'the place')} on the map",
    "list_my_areas": lambda a: "Checking your areas",
    "propose_action": lambda a: f"Preparing an action for you to confirm: {a.get('label', '')}",
    "get_forecast_summary": lambda a: "Reading the 10-day forecast",
    "get_run_summary": lambda a: "Reading this run's results",
    "compare_runs": lambda a: "Comparing two runs",
    "list_shelters": lambda a: "Checking shelters",
    "list_bridges": lambda a: "Checking bridges",
    "list_closed_roads": lambda a: "Checking closed roads",
    "find_shelter_by_name": lambda a: f"Looking up the shelter {a.get('name', '')}",
    "get_historical_summary": lambda a: "Reading past incidents",
    "instant_what_if": lambda a: f"Instant what-if: {a.get('total_mm', '?')} mm in {a.get('hours', '?')} h (AI emulator)",
    "rain_triggers": lambda a: "Reading rain triggers",
}


async def ask_stream(session_id: str, message: str, page: str = "", aoi_id: str | None = None, run_id: str | None = None):
    """Yields events for the chat: {type: step, label} when a tool is called, {type: thought, text} (Gemini thinking
    summaries, streamed), {type: delta, text} (answer text as it is written), then {type: final, ...ask() result}."""
    from google.adk.agents.run_config import RunConfig, StreamingMode
    user = "official"
    aoi_name = ""
    if aoi_id:
        from app.services import firestore as fs
        aoi_name = (fs.get_aoi(aoi_id) or {}).get("name") or ""
    ctx = {"page": page or "home", "aoi_id": aoi_id or "", "aoi_name": aoi_name, "run_id": run_id or "",
           "proposals": [], "sources": [], "search_entry_point": ""}
    if await _sessions.get_session(app_name=APP, user_id=user, session_id=session_id) is None:
        await _sessions.create_session(app_name=APP, user_id=user, session_id=session_id, state=ctx)
    msg = types.Content(role="user", parts=[types.Part(text=message)])
    final_text, calls, streamed, thought_streamed = "", [], "", False
    cfg = RunConfig(streaming_mode=StreamingMode.SSE)
    async for ev in _get_runner().run_async(user_id=user, session_id=session_id, new_message=msg, state_delta=ctx, run_config=cfg):
        if ev.author != "assistant":
            continue
        for p in (ev.content.parts if ev.content and ev.content.parts else []):
            if p.function_call:
                if not ev.partial:
                    calls.append(p.function_call.name)
                    args = dict(p.function_call.args or {})
                    yield {"type": "step", "label": STEP.get(p.function_call.name, lambda a: p.function_call.name)(args)}
            elif p.text and getattr(p, "thought", False):
                if ev.partial:
                    thought_streamed = True
                    yield {"type": "thought", "text": p.text}
                elif not thought_streamed:  # some turns deliver the summary only whole
                    yield {"type": "thought", "text": p.text}
                else:
                    thought_streamed = False  # the whole copy of what was streamed; next turn starts fresh
            elif p.text:
                if ev.partial:
                    streamed += p.text
                    yield {"type": "delta", "text": p.text}
                else:
                    final_text = p.text  # the complete text of this model turn
                    streamed = ""
    st = (await _sessions.get_session(app_name=APP, user_id=user, session_id=session_id)).state
    reply = final_text.strip() or "Sorry, I could not answer that. Please try rephrasing."
    yield {"type": "final", "reply": reply, "proposals": st.get("proposals") or [], "sources": st.get("sources") or [],
           "search_entry_point": st.get("search_entry_point") or "", "tools_called": calls}


async def ask(session_id: str, message: str, page: str = "", aoi_id: str | None = None, run_id: str | None = None) -> dict:
    """{reply, proposals, sources, search_entry_point, tools_called} (the streamed version's final event)."""
    out: dict = {}
    async for e in ask_stream(session_id, message, page, aoi_id, run_id):
        if e["type"] == "final":
            out = {k: v for k, v in e.items() if k != "type"}
    return out
