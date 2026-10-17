"""Tabletop drill (mock exercise) run by Gemini on a stored scenario.

NDMA guidelines ask districts to rehearse their flood response. Here the simulation supplies the truth: a timeline of
what the model says happens hour by hour (rain, roads and bridges closing, the move-before deadline, shelters filling).
Gemini turns it into realistic injects (messages from the control room, IMD, SDRF, a tehsildar, a worried caller) with
the actions a good response would include, then scores each decision the participants type and writes an after-action
report. Injects marked "model" must cite fact ids and quote only numbers from the facts (checked); a few marked
"fictional" add friction (a rumour, a power cut at a shelter) and say so. Without Gemini a plain rule-based drill runs.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.pipeline import facts as F
from app.services import gemini

log = logging.getLogger(__name__)


class Inject(BaseModel):
    hour: int = Field(description="scenario hour (1-based) the message arrives")
    source: str = Field(description="who sends it, e.g. 'District control room', 'IMD Dehradun', 'SDRF team at Ratura'")
    message: str = Field(description="the message as received, 1-3 sentences, plain words")
    kind: Literal["model", "fictional"] = Field(description="model = from the simulation facts; fictional = added friction")
    evidence_ids: list[str] = Field(default_factory=list, description="fact ids the message is based on (model injects)")
    expected_actions: list[str] = Field(description="2-4 actions a good response includes, naming places and resources")
    decide_within_min: int = Field(10, description="minutes the team has to answer")


class DrillPlan(BaseModel):
    title: str
    briefing: str = Field(description="situation at the start, 3-4 sentences, for the District Emergency Operations Centre")
    injects: list[Inject]


class Evaluation(BaseModel):
    score: int = Field(description="0 = harmful or no action, 1 = weak, 2 = adequate, 3 = strong")
    verdict: str = Field(description="one sentence")
    good: list[str] = Field(default_factory=list)
    missed: list[str] = Field(default_factory=list, description="expected actions not covered")
    risk: str = Field("", description="what could go wrong if the decision stands")
    better: str = Field("", description="a stronger decision in one or two sentences")


class Report(BaseModel):
    summary: str
    strengths: list[str]
    gaps: list[str]
    sop_changes: list[str] = Field(description="concrete changes to the district SOP or the flood plan")
    training_needs: list[str]


PLAN_PROMPT = """You are the exercise controller of a tabletop flood drill for a District Emergency Operations Centre in India.
Write 7-9 injects across the scenario hours, in time order, from the TIMELINE and FACTS below (the simulation's output).
Most injects are kind "model": base each on one or more timeline events or facts, cite their ids in evidence_ids, and
quote only numbers that appear in those facts. Add 2 kind "fictional" injects that create realistic friction a district
faces (a WhatsApp rumour, a power cut at a shelter, a request to keep a road open for a VIP visit, a missing person,
media asking for figures) and write "(exercise inject)" at the end of their message. Sources must be plausible Indian
offices (District control room, IMD Meteorological Centre, CWC site, SDRF/NDRF team, Tehsildar, PWD engineer, police
station, a village pradhan, a caller). expected_actions: what a strong response does (who moves, where to, which road or
bridge to close, which shelter to open, which team to stage), naming places from the facts, never bare ids.
Use the words estimated and suggested; never say "will flood" or "safe". Briefing: the situation at hour 1.

TIMELINE (hour-by-hour events from the model):
{timeline}

FACTS:
{facts}
"""

EVAL_PROMPT = """You are scoring one decision in a tabletop flood drill. Be fair, specific and brief, like an experienced
NDRF trainer. Score 0-3 against the expected actions and the facts. Credit sensible actions that are not listed.
A decision that sends people towards a closing road or bridge, or delays a move past the deadline, scores 0-1.

INJECT: {inject}
DECISION BY THE TEAM: {response}
FACTS: {facts}
"""

REPORT_PROMPT = """Write the after-action report of this tabletop flood drill for the District Magistrate: what went well,
the gaps, concrete changes to the district SOP / flood plan, and training needs. Ground every point in the injects,
decisions and scores below; do not invent events.

DRILL: {drill}
"""


def timeline(run: dict, facts: dict) -> list[dict]:
    """Deterministic hour-by-hour events from the run (the drill's ground truth)."""
    H = len(run.get("rain_series_mm_h") or [])
    ev = []
    for h in range(1, H + 1):
        r = run["rain_series_mm_h"][h - 1]
        ev.append({"hour": h, "clock": F.clock(run.get("start_local"), h), "type": "rain", "text": f"rain {r:.0f} mm in hour {h}"})
    for b in facts.get("bridges", []):
        if b.get("first_closed_hour"):
            ev.append({"hour": b["first_closed_hour"], "type": "bridge_closes", "id": b["id"], "text": f"bridge {b.get('place') or b['name']} closes ({b.get('reason')})"})
    for r in facts.get("closed_roads", [])[:6]:
        ev.append({"hour": r["first_closed_hour"], "type": "road_closes", "id": r["id"], "text": f"{r['name']} closes ({r.get('reason')})"})
    for r in facts.get("routes", [])[:6]:
        if r.get("passable_until_h"):
            ev.append({"hour": r["passable_until_h"], "type": "route_cut", "id": r["id"], "text": f"evacuation route from {r.get('from_place')} cut"})
    sc = facts.get("scenario", {})
    if sc.get("move_before_hour"):
        ev.append({"hour": max(1, sc["move_before_hour"] - 1), "type": "deadline", "text": f"people must move {sc.get('move_before')}"})
    k = {x["id"]: x for x in facts.get("key_numbers", [])}
    if "K3" in k and k["K3"]["value"]:
        ev.append({"hour": max(1, (sc.get("move_before_hour") or 2) - 1), "type": "capacity_gap", "id": "K3", "text": f"{k['K3'].get('rounded', k['K3']['value'])} people have no reachable shelter place"})
    if sc.get("worst_hour"):
        ev.append({"hour": sc["worst_hour"], "type": "peak", "id": "K1", "text": f"peak flooding: {k.get('K1', {}).get('rounded', '')} people in flood water"})
    return sorted(ev, key=lambda e: (e["hour"], e["type"] != "rain"))


def _rules_plan(run: dict, facts: dict, tl: list[dict]) -> DrillPlan:
    inj = []
    for e in tl:
        if e["type"] == "rain" and e["hour"] not in (1,):
            continue
        acts = {"bridge_closes": ["Close the bridge to traffic and post police at both ends", "Divert evacuation routes"],
                "road_closes": ["Close the road and post a diversion", "Re-route anyone still moving"],
                "route_cut": ["Move remaining people by another route before it closes", "Tell the receiving shelter"],
                "deadline": ["Order the evacuation of the exposed clusters now", "Open the assigned shelters and staging points"],
                "capacity_gap": ["Open additional shelters or arrange transport out", "Ask the SDRF for help with transport"],
                "peak": ["Keep everyone out of flooded streets", "Stage medical teams near the worst-hit clusters"],
                "rain": ["Activate the district EOC", "Alert the clusters at risk"]}[e["type"]]
        inj.append(Inject(hour=e["hour"], source="District control room", message=e["text"].capitalize() + ".", kind="model",
                          evidence_ids=[e["id"]] if e.get("id") else [], expected_actions=acts))
    return DrillPlan(title=f"Flood drill: {facts['scenario'].get('label', '')}"[:120],
                     briefing=F.bottom_line(facts), injects=inj[:9])


def _grounded(inj: Inject, facts: dict) -> bool:
    if inj.kind == "fictional":
        return True
    idx = F.fact_index(facts)
    items = [idx[i] for i in inj.evidence_ids if i in idx]
    if not items:
        return False
    vals = F._fact_numbers(items + list(facts.get("key_numbers", [])), facts)
    hours = list(range(0, 25))
    return all(F._ok_number(n, vals + hours) for n in F._numbers(inj.message))


def new_drill(run: dict, participant: str = "") -> dict:
    facts = F.build_facts(run)
    tl = timeline(run, facts)
    source, dropped = "rules", 0
    plan = None
    try:
        plan = gemini.generate_json(PLAN_PROMPT.format(timeline=json.dumps(tl, separators=(",", ":")),
                                                       facts=json.dumps(facts, separators=(",", ":"))), DrillPlan, tier="pro", temperature=0.4)
        H = len(run.get("rain_series_mm_h") or [1])
        keep = [i for i in plan.injects if _grounded(i, facts) and 1 <= i.hour <= H]
        dropped = len(plan.injects) - len(keep)
        plan = DrillPlan(title=plan.title, briefing=plan.briefing, injects=sorted(keep, key=lambda i: i.hour)) if len(keep) >= 4 else None
        source = "gemini" if plan else "rules"
    except Exception as e:  # noqa: BLE001
        log.warning("drill plan fell back to rules: %s", e)
    if plan is None:
        plan = _rules_plan(run, facts, tl)
    return {"drill_id": uuid.uuid4().hex[:12], "run_id": run["run_id"], "aoi_id": run["aoi_id"], "participant": participant[:80],
            "created_at": datetime.now(timezone.utc).isoformat(), "source": source, "dropped_ungrounded": dropped,
            "model": gemini.model_name("pro") if source == "gemini" else None, "start_local": run.get("start_local"),
            "plan": plan.model_dump(), "timeline": tl, "responses": {}, "report": None}


def evaluate(drill: dict, run: dict, index: int, response: str) -> dict:
    inj = drill["plan"]["injects"][index]
    facts = F.build_facts(run)
    try:
        ev = gemini.generate_json(EVAL_PROMPT.format(inject=json.dumps(inj), response=response[:2000],
                                                     facts=json.dumps(facts, separators=(",", ":"))), Evaluation, tier="fast", temperature=0.2)
        out = ev.model_dump() | {"by": "gemini"}
    except Exception as e:  # noqa: BLE001
        log.warning("drill evaluation fell back to keywords: %s", e)
        words = set(response.lower().split())
        hit = [a for a in inj["expected_actions"] if len(set(a.lower().split()) & words) >= 2]
        out = {"score": min(3, len(hit) + (1 if response.strip() else 0)), "verdict": "Scored by keyword match (Gemini unavailable).",
               "good": hit, "missed": [a for a in inj["expected_actions"] if a not in hit], "risk": "", "better": "", "by": "rules"}
    out["score"] = max(0, min(3, int(out["score"])))
    return {"response": response[:2000], "at": datetime.now(timezone.utc).isoformat(), **out}


def report(drill: dict) -> dict:
    slim = {"title": drill["plan"]["title"], "injects": [
        {**i, "decision": drill["responses"].get(str(k), {}).get("response"), "score": drill["responses"].get(str(k), {}).get("score"),
         "missed": drill["responses"].get(str(k), {}).get("missed")} for k, i in enumerate(drill["plan"]["injects"])]}
    scores = [r["score"] for r in drill["responses"].values()]
    try:
        rep = gemini.generate_json(REPORT_PROMPT.format(drill=json.dumps(slim, separators=(",", ":"))), Report, tier="pro", temperature=0.3).model_dump()
        rep["by"] = "gemini"
    except Exception as e:  # noqa: BLE001
        log.warning("drill report fell back to rules: %s", e)
        missed = [m for r in drill["responses"].values() for m in r.get("missed", [])]
        rep = {"summary": f"{len(scores)} of {len(drill['plan']['injects'])} injects answered.", "strengths": [],
               "gaps": missed[:8], "sop_changes": [], "training_needs": [], "by": "rules"}
    rep["score"] = round(sum(scores) / (3 * len(drill["plan"]["injects"])) * 100) if drill["plan"]["injects"] else 0
    rep["answered"] = len(scores)
    return rep
