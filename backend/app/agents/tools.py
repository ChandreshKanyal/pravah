"""S14.2 analyst tools: plain functions with type hints and docstrings (ADK wraps them as FunctionTools).

Each returns a compact dict (< 4 KB) of ids and numbers, never arrays. The session state carries `aoi_id` and the
current `run_id`; `run_scenario` updates `run_id` and records `new_run_id` for the API response.
"""
import difflib
import json
import logging
from collections import OrderedDict

from google.adk.tools import ToolContext

from app.models.scenario import ScenarioParams, apply_rain_change
from app.pipeline import facts as F
from app.services import firestore as fs
from app.services import storage

log = logging.getLogger(__name__)
_runs: "OrderedDict[str, dict]" = OrderedDict()  # recent run documents (each up to ~1 MB), the oldest dropped first
MAX_RUNS = 32


def load_run(run_id: str) -> dict:
    if run_id not in _runs:
        doc = fs.get_doc("runs", run_id)
        if not doc:
            raise KeyError(f"unknown run {run_id}")
        remember_run(doc)
    _runs.move_to_end(run_id)
    return _runs[run_id]


def remember_run(run: dict) -> None:
    _runs[run["run_id"]] = run
    while len(_runs) > MAX_RUNS:  # it kept every run the assistant ever read, for the life of the instance
        _runs.popitem(last=False)


def run_summary(run: dict) -> dict:
    e = run.get("exposure", {})
    br = e.get("buildings_by_risk", {})
    bridges = run.get("bridges", [])
    shel = run.get("shelters", [])
    p = run["params"]
    return {
        "run_id": run["run_id"], "rain": run["rain_label"], "hours": len(run["rain_series_mm_h"]),
        "rain_mm_h": [round(x, 1) for x in run["rain_series_mm_h"]][:24],
        "travel_mode": p.get("travel_mode"), "disabled_shelters": p.get("disabled_shelter_ids", []),
        "blocked_areas": len(p.get("blocked_polygons", [])), "extra_shelters": len(p.get("extra_shelters", [])),
        "people_in_flood_water_peak": max(e.get("exposed_pop_by_hour") or [0]),
        "buildings_high_or_critical": br.get("critical", 0) + br.get("high", 0),
        "flooded_km2_worst_hour": (run.get("flooded_area_km2_by_hour") or [0])[-1],
        "people_to_evacuate": run.get("people_to_evacuate", 0), "capacity_gap": run.get("capacity_gap_people", 0),
        "usable_shelters": sum(1 for s in shel if s["status"] == "usable"), "shelters_total": len(shel),
        "bridges_closing": [{"id": b["id"], "hour": b["first_closed_hour"]} for b in bridges if b.get("first_closed_hour")][:8],
        "top_clusters": [{"id": c["id"], "people": c["people"], "risk": c["risk_class"]} for c in e.get("clusters", [])[:5]],
        "warnings": [w[:160] for w in run.get("warnings", [])[:5]],
    }


def _current(tool_context: ToolContext, run_id: str | None) -> dict:
    rid = run_id or tool_context.state.get("run_id")
    if not rid:
        raise KeyError("no run yet: call run_scenario first")
    return load_run(rid)


def get_forecast_summary(tool_context: ToolContext) -> dict:
    """10-day rain forecast for the current area: daily totals, the wettest day and a one-reach screening badge.

    Returns:
        days (date, precip_mm, badge), worst_day_index, provider and attribution.
    """
    from app.api.forecast import forecast
    fc = forecast(tool_context.state["aoi_id"], 4)
    days = [{"i": i, "date": s["date"], "precip_mm": round(s["precip_mm"], 1), "badge": s["badge"]}
            for i, s in enumerate(fc.get("screening", []))]
    past = fc.get("past_90d") or []
    past15 = round(sum((d.get("mm") or 0) for d in past[-15:]), 1) if past else None
    return {"days": days, "worst_day_index": fc.get("worst_day_index"), "past_15_days_rain_mm": past15,
            "attribution": fc.get("attribution"), "warnings": fc.get("warnings", [])}


def run_scenario(tool_context: ToolContext, rain_source: str | None = None, manual_intensity_mm_h: float | None = None,
                 duration_h: int | None = None, hyetograph: str | None = None, forecast_day_index: int | None = None,
                 worst_multiplier: float | None = None, river_offset_m: float | None = None,
                 upstream_inflow_m3s: float | None = None,
                 pop_multiplier: float | None = None, travel_mode: str | None = None, evac_start_hour: int | None = None,
                 disable_shelter_ids: list[str] | None = None, enable_shelter_ids: list[str] | None = None,
                 bridge_margin_m: float | None = None) -> dict:
    """Run a what-if scenario: copies the current run's settings and changes only the arguments given.

    Args:
        rain_source: one of forecast, worst, best, historical_extreme, manual.
        manual_intensity_mm_h: rain intensity for manual rain (5-150 mm/h); setting it implies rain_source=manual.
        duration_h: hours simulated (1-24).
        hyetograph: constant or triangular_front.
        forecast_day_index: forecast day 0-9 (for forecast/worst/best).
        worst_multiplier: multiplier for the worst case (e.g. 1.5).
        river_offset_m: extra river level already present (-1 to 5 m).
        upstream_inflow_m3s: river flow entering the area from upstream in m3/s (e.g. from a CWC flood forecast).
        pop_multiplier: population multiplier (0.5-2).
        travel_mode: walk or drive.
        evac_start_hour: hour the evacuation starts (1-based).
        disable_shelter_ids: shelter ids to close (e.g. ["S3"]).
        enable_shelter_ids: shelter ids to reopen.
        bridge_margin_m: close a bridge when the river is within this many metres of its deck (0 = at the deck).

    Returns:
        A summary of the new run with its run_id, and previous_run_id for comparison.
    """
    from app.pipeline.run_pipeline import run_pipeline
    prev_id = tool_context.state.get("run_id")
    base = load_run(prev_id)["params"] if prev_id else {"aoi_id": tool_context.state["aoi_id"]}
    p = dict(base)
    for k, v in dict(rain_source=rain_source, manual_intensity_mm_h=manual_intensity_mm_h, duration_h=duration_h,
                     hyetograph=hyetograph, forecast_day_index=forecast_day_index, worst_multiplier=worst_multiplier,
                     river_offset_m=river_offset_m, upstream_inflow_m3s=upstream_inflow_m3s, pop_multiplier=pop_multiplier, travel_mode=travel_mode,
                     evac_start_hour=evac_start_hour, bridge_margin_m=bridge_margin_m).items():
        if v is not None:
            p[k] = v
    if manual_intensity_mm_h is not None:
        p["rain_preset"] = None  # an explicit intensity replaces an IMD category
        if rain_source is None:
            p["rain_source"] = "manual"
    given = {k for k, v in dict(rain_source=rain_source, manual_intensity_mm_h=manual_intensity_mm_h, duration_h=duration_h,
                                 hyetograph=hyetograph, forecast_day_index=forecast_day_index, worst_multiplier=worst_multiplier).items()
             if v is not None} | ({"rain_preset", "rain_source"} if manual_intensity_mm_h is not None else set())
    apply_rain_change(p, given)
    dis = set(p.get("disabled_shelter_ids", [])) | set(disable_shelter_ids or [])
    p["disabled_shelter_ids"] = sorted(dis - set(enable_shelter_ids or []))
    params = ScenarioParams(**p)
    params.duration_h = max(1, min(24, params.duration_h))
    params.manual_intensity_mm_h = max(0.0, min(300.0, params.manual_intensity_mm_h))
    run = run_pipeline(params).model_dump(mode="json")
    remember_run(run)
    tool_context.state["run_id"] = run["run_id"]
    tool_context.state["new_run_id"] = run["run_id"]
    return {**run_summary(run), "previous_run_id": prev_id}


def get_run_summary(tool_context: ToolContext, run_id: str | None = None) -> dict:
    """Key numbers of a run (default: the current run).

    Args:
        run_id: a run id; omit for the current run.
    """
    return run_summary(_current(tool_context, run_id))


def compare_runs(tool_context: ToolContext, run_id_a: str, run_id_b: str) -> dict:
    """Differences between two runs (b minus a) in the key numbers.

    Args:
        run_id_a: the earlier/base run id.
        run_id_b: the later/what-if run id.
    """
    a, b = run_summary(load_run(run_id_a)), run_summary(load_run(run_id_b))
    diff = {}
    for k in ("people_in_flood_water_peak", "buildings_high_or_critical",
              "flooded_km2_worst_hour", "people_to_evacuate", "capacity_gap", "usable_shelters"):
        diff[k] = {"a": a[k], "b": b[k], "change": round(b[k] - a[k], 3)}
    ba = {x["id"]: x["hour"] for x in a["bridges_closing"]}
    bb = {x["id"]: x["hour"] for x in b["bridges_closing"]}
    return {"a": {"run_id": run_id_a, "rain": a["rain"]}, "b": {"run_id": run_id_b, "rain": b["rain"]}, "diff": diff,
            "bridges_newly_closing": sorted(set(bb) - set(ba)), "bridges_no_longer_closing": sorted(set(ba) - set(bb))}


def list_shelters(tool_context: ToolContext, run_id: str | None = None) -> dict:
    """Shelters and assembly points with capacity, people assigned, spare places and status.

    Args:
        run_id: a run id; omit for the current run.
    """
    run = _current(tool_context, run_id)
    return {"run_id": run["run_id"], "shelters": [
        {"id": s["id"], "name": s["name"][:40], "capacity": s["capacity"], "assigned": s["assigned"], "spare": s["spare"],
         "status": s["status"], "capacity_confidence": s.get("capacity_confidence")} for s in run["shelters"]][:30]}


def list_bridges(tool_context: ToolContext, run_id: str | None = None) -> dict:
    """Bridges with the first hour each closes (null = stays open) and why, earliest first.

    Args:
        run_id: a run id; omit for the current run.
    """
    run = _current(tool_context, run_id)
    return {"run_id": run["run_id"], "hours": len(run["rain_series_mm_h"]), "bridges": [
        {"id": b["id"], "name": b["name"][:40], "first_closed_hour": b.get("first_closed_hour"), "reason": b.get("reason")}
        for b in run["bridges"]][:30]}


def list_closed_roads(tool_context: ToolContext, hour: int | None = None, run_id: str | None = None) -> dict:
    """Roads closed by a given hour, grouped by road name, longest first, with the reason (flood, bridge, blocked).

    Args:
        hour: scenario hour (1-based); omit for the last hour.
        run_id: a run id; omit for the current run.
    """
    run = _current(tool_context, run_id)
    roads = F.closed_roads(run, hour)
    return {"run_id": run["run_id"], "hour": hour or len(run["rain_series_mm_h"]), "segments": len(roads),
            "roads": [{"name": r["name"][:40], "length_km": r["length_km"], "first_closed_hour": r["first_closed_hour"],
                       "reason": r["reason"]} for r in roads[:15]]}


def find_shelter_by_name(tool_context: ToolContext, name: str) -> dict:
    """Find shelter ids whose name best matches the given text (fuzzy).

    Args:
        name: part of a shelter name, e.g. "school" or "Gurudwara".
    """
    shelters = storage.get_json(tool_context.state["aoi_id"], "shelters.json")
    q = name.lower()
    scored = sorted(((difflib.SequenceMatcher(None, q, s["name"].lower()).ratio() + (0.5 if q in s["name"].lower() else 0),
                      s) for s in shelters), key=lambda x: -x[0])
    return {"matches": [{"id": s["id"], "name": s["name"], "kind": s.get("kind"), "score": round(sc, 2)}
                        for sc, s in scored[:5] if sc > 0.3]}


def get_historical_summary(tool_context: ToolContext) -> dict:
    """Recorded past floods (Global Flood Database) for the current area, plus web leads
    if they were fetched."""
    from app.services import history
    h = history.aoi_history(tool_context.state["aoi_id"], fetch_web=False)
    return json.loads(json.dumps({k: (v[:10] if isinstance(v, list) else v) for k, v in h.items()}, default=str))


def instant_what_if(tool_context: ToolContext, total_mm: float, hours: int, early_peak: bool = True,
                    river_offset_m: float = 0.0) -> dict:
    """Instant estimate of the 2D water model's peak flood for a storm, from the area's AI emulator (milliseconds,
    no routes or shelters). Use it for quick "what if X mm falls in Y hours" questions; use run_scenario for a full plan.

    Args:
        total_mm: storm total in mm.
        hours: storm duration, 1-6 hours.
        early_peak: True for an early-peaked storm (most rain in the first hours), False for steady rain.
        river_offset_m: river level above normal in metres (river areas).

    Returns:
        flooded_km2, people_in_water_30cm (residents at home in water at least 30 cm deep), max_depth_m, the IMD
        category of the storm, and outside_trained_range (non-empty = less reliable).
    """
    from app.pipeline import emulator
    h, st = emulator.predict(tool_context.state["aoi_id"], float(total_mm), int(max(1, min(24, hours))),
                             "triangular_front" if early_peak else "constant", float(river_offset_m))
    if h is None:
        return {"error": "The AI emulator is not trained for this area yet (What-if tab)."}
    return {"flooded_km2": st["flooded_km2"], "people_in_water_30cm": st["people_in_water"], "max_depth_m": st["max_depth_m"],
            "imd_category": st["imd_category"], "outside_trained_range": st["outside_trained_range"], "source": "AI emulator of the 2D model"}


def rain_triggers(tool_context: ToolContext, place: str | None = None) -> dict:
    """Rain triggers for early action: per village or neighbourhood, the smallest early-peaked storm (mm in 1, 3 and 6
    hours) that puts at least 25 people (or 5% of residents) in water 30 cm deep at home, from the 2D water model.

    Args:
        place: a place name to look up (fuzzy); omit for the most exposed places.

    Returns:
        places (name, residents, thresholds_mm by duration, IMD category by duration) and the method note.
    """
    from app.pipeline import emulator
    t = emulator.triggers_json(tool_context.state["aoi_id"])
    if not t:
        return {"error": "No triggers yet: train the AI emulator for this area (What-if tab)."}
    rows = t["places"]
    if place:
        names = [r["name"] for r in rows]
        hit = difflib.get_close_matches(place, names, n=3, cutoff=0.5)
        rows = [r for r in rows if r["name"] in hit]
        if not rows:
            return {"places": [], "note": f"No trigger for '{place}': it does not flood within the trained storms, or the name is not an OSM place here."}
    return {"places": [{k: r[k] for k in ("name", "residents", "thresholds_mm", "imd")} for r in rows[:8]],
            "depth_m": t["depth_m"], "note": t.get("note", "")}


TOOLS = [get_forecast_summary, run_scenario, get_run_summary, compare_runs, list_shelters, list_bridges,
         list_closed_roads, find_shelter_by_name, get_historical_summary, instant_what_if, rain_triggers]
