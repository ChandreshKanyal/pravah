"""S11.4 historian: an ADK LlmAgent whose only tool is the built-in google_search (built-in tools must sit in their
own agent). Results are unverified leads with source URLs; places are geocoded for display markers only."""
import asyncio
import json
import logging
import re
import uuid

import requests
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import google_search
from google.genai import types

import app.agents  # noqa: F401  (Vertex env)
from app.config import get_settings
from app.services import gemini

log = logging.getLogger(__name__)

PROMPT = """List documented floods, flash floods and cloudbursts affecting {place} ({bbox}) since 2000.
Return JSON only: [{{"type": "...", "date": "YYYY-MM-DD or approximate", "place": "...", "summary": "<= 30 words",
"source_urls": ["..."]}}]. Only include events with a source URL. If unsure of the date, say "approximate".
At most 12 events, most significant first."""


def _agent() -> LlmAgent:
    return LlmAgent(name="historian", model=gemini.adk_model(get_settings().gemini_model_fast), tools=[google_search],
                    instruction="You find documented natural-hazard incidents with web sources. Answer only in JSON.",
                    generate_content_config=types.GenerateContentConfig(temperature=0.1))


def _parse(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return []
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for it in items if isinstance(items, list) else []:
        urls = [u for u in (it.get("source_urls") or []) if isinstance(u, str) and u.startswith("http")]
        if urls:
            out.append({"type": str(it.get("type", ""))[:40], "date": str(it.get("date", "approximate"))[:20],
                        "place": str(it.get("place", ""))[:80], "summary": str(it.get("summary", ""))[:300],
                        "source_urls": urls[:3]})
    return out


def _geocode(place: str, bbox) -> dict | None:
    """Display-only marker position from the Maps Geocoding API, biased to the AOI."""
    from app.services.weather import maps_server_key
    try:
        w, s, e, n = bbox
        r = requests.get("https://maps.googleapis.com/maps/api/geocode/json", timeout=10,
                         params={"address": place, "bounds": f"{s},{w}|{n},{e}", "region": "in", "key": maps_server_key()})
        res = r.json().get("results") or []
        if res:
            loc = res[0]["geometry"]["location"]
            return {"lat": loc["lat"], "lng": loc["lng"]}
    except Exception as ex:
        log.info("geocode failed for %s: %s", place, ex)
    return None


async def _run(place: str, bbox, prompt: str = PROMPT) -> tuple[str, dict, list]:
    ss = InMemorySessionService()
    sid = uuid.uuid4().hex
    await ss.create_session(app_name="pravah_hist", user_id="historian", session_id=sid)
    runner = Runner(app_name="pravah_hist", agent=_agent(), session_service=ss)
    msg = types.Content(role="user", parts=[types.Part(text=prompt.format(place=place, bbox=bbox))])
    text, entry, sources = "", "", []
    async for ev in runner.run_async(user_id="historian", session_id=sid, new_message=msg):
        gm = getattr(ev, "grounding_metadata", None)
        if gm:
            if gm.search_entry_point and gm.search_entry_point.rendered_content:
                entry = gm.search_entry_point.rendered_content  # Search suggestions must be shown (grounding terms)
            for ch in gm.grounding_chunks or []:
                if ch.web and ch.web.uri:
                    sources.append({"title": ch.web.title or "", "uri": ch.web.uri})
        for p in (ev.content.parts if ev.content and ev.content.parts else []):
            if p.text and not getattr(p, "thought", False):
                text += p.text
    return text, entry, sources


def search(place: str, bbox, prompt: str = PROMPT) -> tuple[str, str, list]:
    """Runs the search agent in its own event loop (called from sync code): (answer text, entry point html, sources)."""
    try:
        return asyncio.run(_run(place, bbox, prompt))
    except RuntimeError:  # already inside an event loop
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_run(place, bbox, prompt))
        finally:
            loop.close()


def find_incidents(place: str, bbox) -> dict:
    """{incidents, sources, search_entry_point}."""
    text, entry, sources = search(place, bbox)
    items = _parse(text)
    for it in items:
        it["marker"] = _geocode(f"{it['place']}, India", bbox) if bbox else None
    return {"incidents": items, "sources": sources[:12], "search_entry_point": entry}
