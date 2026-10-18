"""Why this shelter, why this route: Gemini explains a run's choice in plain words from the run's own facts only
(the shelter checks and route facts computed in pipeline/evac.py). Nothing is looked up or invented; numbers come
from the facts as given. Cached per run (runs never change after they finish)."""
import json
import logging

from pydantic import BaseModel

from app.pipeline.evac import CAUTION_PENALTY_S, FREEBOARD_M, GUIDE_KM
from app.services import gemini

log = logging.getLogger(__name__)

KINDS = {"school": "school", "college": "college", "university": "university", "community_centre": "community centre",
         "townhall": "town hall", "social_facility": "social facility", "place_of_worship": "place of worship (large hall)",
         "candidate_large_building": "large building (unverified candidate)", "assembly_point": "open assembly ground",
         "user_added": "shelter added by an official"}

RULES = f"""How Pravah chooses shelters in a scenario (use these to explain; do not add others):
- Candidates: schools, colleges, community centres, town halls and social facilities from OpenStreetMap (places of
  worship need confirmation; large solid buildings on high ground are unverified stand-ins when few are mapped), open
  high ground as assembly points, and shelters officials add.
- A shelter is excluded if flood water reaches its own 30 m cell at any hour of the scenario, if officials closed it,
  or if no road to it is open at the evacuation hour.
- Freeboard: its ground should stand at least {FREEBOARD_M} m above the peak flood water on lower ground within 150 m
  (the Indian Standards plinth rule, IS 14264 / IS 15690). Below that it is still usable but people are sent to one
  with margin first ({int(CAUTION_PENALTY_S // 60)} minutes' penalty in the assignment).
- Isolation: a shelter whose door roads all close during the scenario can be cut off (American Red Cross shelter
  standard ARC 4496 says to avoid such buildings); same penalty.
- Distance: Odisha's coastal shelter plan aims for a shelter within {GUIDE_KM} km of every home.
- Space: 3.5 m2 of floor per person (Sphere minimum), 60% of the floor usable.
- People are assigned to minimise total travel time within each shelter's capacity (a transportation problem); routes
  are the quickest open roads at the evacuation hour, avoiding roads flooded beyond the walking limit, steep stretches
  and crowding.
"""

PROMPT = """You explain one decision of a flood evacuation plan to an Indian district official.
{rules}
Facts for this {what} (JSON; the only facts you may use):
{facts}

Name an unnamed or "Large building ..." shelter by its place (e.g. "the large building near X"), not by its code.
Write: a one-line headline; 2-4 short reasons it was chosen (or, if it is not used, why not); 0-3 cautions to check
on the ground. Use the numbers exactly as given, in plain words. Never call anything "safe": say it stays dry or keeps
margin in this scenario. Do not mention JSON, field names or penalties in minutes unless they explain the choice."""


class Explanation(BaseModel):
    headline: str
    reasons: list[str]
    cautions: list[str]


def shelter_facts(run: dict, sid: str) -> dict | None:
    s = next((x for x in run.get("shelters", []) if x.get("id") == sid), None)
    if not s:
        return None
    usable = [x for x in run.get("shelters", []) if x.get("status") == "usable"]
    p = run.get("params", {})
    return {"shelter": {k: s.get(k) for k in ("id", "name", "place", "status", "capacity", "assigned", "spare", "capacity_confidence",
                                             "floors", "area_m2", "note", "routes_in", "farthest_km", "slowest_min", "checks")}
            | {"type": KINDS.get(s.get("kind", ""), s.get("kind", ""))},
            "scenario": {"rain": run.get("rain_label"), "travel_mode": p.get("travel_mode", "walk"),
                         "max_travel_min": p.get("max_travel_min"), "evacuation_hour": p.get("evac_start_hour"),
                         "people_to_move": run.get("people_to_evacuate"), "capacity_gap_people": run.get("capacity_gap_people")},
            "other_usable_shelters": len(usable) - (1 if s.get("status") == "usable" else 0),
            "other_usable_with_margin": sum(1 for x in usable if x.get("id") != sid and not (x.get("checks") or {}).get("flags"))}


def route_facts(run: dict, route: dict) -> dict:
    sh = next((x for x in run.get("shelters", []) if x.get("id") == route.get("to_shelter")), {})
    p = run.get("params", {})
    keep = ("to_shelter", "place", "people", "eta_min", "access_min", "length_km", "passable_until_h", "margin_h",
            "use_now_gone_soon", "main_road_share", "via", "bridges_on_route", "steep_m", "crowding", "max_water_m")
    return {"route": {k: route.get(k) for k in keep},
            "shelter": {"name": sh.get("name"), "place": sh.get("place"), "type": KINDS.get(sh.get("kind", ""), sh.get("kind", "")), "checks": sh.get("checks")},
            "scenario": {"rain": run.get("rain_label"), "travel_mode": p.get("travel_mode", "walk"),
                         "walk_depth_limit_m": p.get("walk_depth_limit_m"), "evacuation_hour": p.get("evac_start_hour"),
                         "hours": len(run.get("rain_series_mm_h") or [])}}


def explain(what: str, facts: dict) -> dict:
    out = gemini.generate_json(PROMPT.format(rules=RULES, what=what, facts=json.dumps(facts, ensure_ascii=False, default=str)),
                               Explanation, temperature=0.2)
    return out.model_dump()
