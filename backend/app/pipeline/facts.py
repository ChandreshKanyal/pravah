"""S15.1 facts, S15.3 validator, S15.4 rules fallback. Deterministic; never calls Gemini.

Every fact item carries an id so advice can cite it; the validator only accepts ids and numbers that exist here.
"""
import json
import logging
import math
import re
from collections import defaultdict

from app.models.advisory import DISCLAIMER, Advisory, Recommendation
from app.services import storage

log = logging.getLogger(__name__)
MAX_FACTS_BYTES = 12_000


def _hav_m(a, b) -> float:
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = p2 - p1, math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def _road_groups(roads: dict, keep) -> list[dict]:
    """Physical road segments (both directions merged) grouped by name; `keep(props)` selects features."""
    groups: dict[str, dict] = {}
    seen = set()
    for f in roads.get("features", []):
        pr = f["properties"]
        if not keep(pr):
            continue
        cs = f["geometry"]["coordinates"]
        key = frozenset([tuple(round(x, 5) for x in cs[0]), tuple(round(x, 5) for x in cs[-1])])
        if key in seen:
            continue
        seen.add(key)
        name = pr.get("name") or f"unnamed {pr.get('highway') or 'road'}"
        g = groups.setdefault(name, {"name": name, "length_m": 0.0, "first_closed_hour": None, "reason": pr.get("reason"),
                                     "lsi_max": 0, "lonlat": cs[len(cs) // 2]})
        g["length_m"] += pr.get("length_m") or sum(_hav_m(a, b) for a, b in zip(cs[:-1], cs[1:]))
        h = pr.get("first_closed_hour")
        if h is not None and (g["first_closed_hour"] is None or h < g["first_closed_hour"]):
            g["first_closed_hour"], g["reason"] = h, pr.get("reason")
        g["lsi_max"] = max(g["lsi_max"], pr.get("lsi_max") or 0)
    out = sorted(groups.values(), key=lambda g: -g["length_m"])
    for g in out:
        g["length_km"] = round(g.pop("length_m") / 1000, 2)
        g["lonlat"] = [round(g["lonlat"][0], 5), round(g["lonlat"][1], 5)]
    return out


def load_roads(run_id: str) -> dict:
    try:
        return json.loads(storage.get_run(run_id, "roads.geojson"))
    except Exception:
        return {"features": []}


def closed_roads(run: dict, hour: int | None = None, roads: dict | None = None) -> list[dict]:
    H = len(run["rain_series_mm_h"])
    hour = H if hour is None else int(hour)
    roads = roads if roads is not None else load_roads(run["run_id"])
    return _road_groups(roads, lambda p: p.get("first_closed_hour") is not None and p["first_closed_hour"] <= hour)


def _ll(x: dict) -> list[float] | None:
    if "lon" in x and "lat" in x:
        return [x["lon"], x["lat"]]
    return x.get("centroid") or x.get("lonlat")


def build_facts(run: dict, area_extra: dict | None = None) -> dict:
    """Compact, id-keyed facts for one run (S15.1). `area_extra` may carry medical, crowding, forecast, history."""
    area_extra = area_extra or {}
    e = run.get("exposure", {})
    H = len(run["rain_series_mm_h"])
    roads = load_roads(run["run_id"])
    bridges = run.get("bridges", [])
    closing = [b for b in bridges if b.get("first_closed_hour")]
    peak = max(e.get("exposed_pop_by_hour") or [0])
    ls_peak = max(e.get("landslide_exposed_pop_by_hour") or [0])
    br = e.get("buildings_by_risk", {})
    key = [
        {"id": "K1", "label": "People in flood water (peak, depth >= 0.05 m)", "value": peak, "unit": "people"},
        {"id": "K2", "label": "Buildings at high or critical estimated risk", "value": br.get("critical", 0) + br.get("high", 0),
         "unit": "buildings"},
        {"id": "K3", "label": "Capacity gap (people with no reachable shelter place)", "value": run.get("capacity_gap_people", 0),
         "unit": "people"},
        {"id": "K4", "label": "Bridges closing in the scenario", "value": len(closing), "unit": f"of {len(bridges)} bridges"},
        {"id": "K5", "label": "Flooded area at the worst hour", "value": (run.get("flooded_area_km2_by_hour") or [0])[-1],
         "unit": "km2"},
        {"id": "K6", "label": "People in landslide hazard zones (peak)", "value": ls_peak, "unit": "people"},
        {"id": "K7", "label": "People who need to move", "value": run.get("people_to_evacuate", 0), "unit": "people"},
    ]
    clusters = [{"id": c["id"], "people": c["people"], "max_depth_m": c["max_depth"], "risk_class": c["risk_class"],
                 "dominant_class": c["dominant_class"], "lonlat": c["centroid"]} for c in e.get("clusters", [])[:10]]
    shelters = [{"id": s["id"], "name": s["name"], "kind": s.get("kind", ""), "capacity": s["capacity"],
                 "assigned": s["assigned"], "spare": s["spare"], "status": s["status"],
                 "capacity_confidence": s.get("capacity_confidence", ""), "lonlat": [s["lon"], s["lat"]]}
                for s in run.get("shelters", []) if s.get("kind") != "assembly_point" or s.get("assigned", 0) > 0][:20]
    routes = []
    for k, r in enumerate(run.get("routes", [])[:12], start=1):
        frm = None
        if "from_lon" in r and clusters:
            d, c = min((_hav_m([r["from_lon"], r["from_lat"]], c["lonlat"]), c["id"]) for c in clusters)
            frm = c if d <= 600 else None
        routes.append({"id": f"RT{k}", "from_cluster": frm, "to": r["to_shelter"], "people": r["people"],
                       "eta_min": r["eta_min"], "passable_until_h": r.get("passable_until_h"),
                       "use_now_gone_soon": r.get("use_now_gone_soon", False),
                       "lonlat": [r["from_lon"], r["from_lat"]] if "from_lon" in r else None})
    closed = [{"id": f"R{k}", **g} for k, g in enumerate(_road_groups(
        roads, lambda p: p.get("first_closed_hour") is not None), start=1)][:15]
    lsr = [{"id": f"L{k}", **{x: g[x] for x in ("name", "length_km", "lsi_max", "lonlat")}} for k, g in enumerate(
        _road_groups(roads, lambda p: (p.get("lsi_max") or 0) >= 4), start=1)][:10]
    meta = run.get("methods", {})
    facts = {
        "scenario": {"label": run["rain_label"], "H": H, "worst_hour": H,
                     "peak_rain_mm_h": round(max(run["rain_series_mm_h"] or [0]), 1),
                     "total_rain_mm": round(sum(run["rain_series_mm_h"]), 1),
                     "landslide_trigger_hours": meta.get("landslide_trigger_hours", []),
                     "landslide_threshold": meta.get("landslide_threshold", "")},
        "key_numbers": key,
        "clusters": clusters,
        "shelters": shelters,
        "bridges": [{"id": b["id"], "name": b["name"], "first_closed_hour": b.get("first_closed_hour"),
                     "reason": b.get("reason"), "lonlat": [b["lon"], b["lat"]]} for b in bridges if b.get("first_closed_hour")][:12],
        "closed_roads": closed,
        "routes": routes,
        "assembly_points": [{"id": a["id"], "capacity": a["capacity"], "area_m2": round(a.get("area_m2", 0)),
                             "lonlat": [a["lon"], a["lat"]]} for a in run.get("assembly_points", [])[:6]],
        "staging_points": [{"id": g["id"], "near_cluster": g.get("near_cluster"), "lonlat": [g["lon"], g["lat"]]}
                           for g in run.get("staging_points", [])],
        "medical": [{"id": m["id"], "name": m.get("name") or "", "lonlat": _ll(m)} for m in area_extra.get("medical", [])][:6],
        "hotspots": [{"id": h["id"], "type": h["type"], "upa_km2": h["upa_km2"], "stage_m": h.get("stage_m"),
                      "depth_m": h.get("depth_m"), "lonlat": [h["lon"], h["lat"]]} for h in run.get("hotspots", [])[:6]],
        "landslide_roads": lsr,
        "crowding": [{"id": x["id"], "score": x["score"], "attractors": x.get("top_attractors", []),
                      "lonlat": [x["lon"], x["lat"]]} for x in area_extra.get("crowding", [])[:5]],
        "drains": [{"id": d["id"], "type": d["type"], "name": d.get("name", ""), "priority": d["priority"],
                    "exposed_people_300m": d.get("exposed_people_300m"), "photo_condition": d.get("photo_condition"),
                    "lonlat": [d["lon"], d["lat"]]} for d in (run.get("drains") or area_extra.get("drains", []))[:10]],
        "verification_queue": [{"id": f"V{k}", "bid": v["bid"], "current_class": v["current_class"], "people": v["people"],
                                "lonlat": [v["lon"], v["lat"]]} for k, v in enumerate(area_extra.get("verification", [])[:10], 1)],
        "forecast": area_extra.get("forecast", {}),
        "history": area_extra.get("history", {}),
        "warnings": run.get("warnings", [])[:10],
    }
    _trim(facts)
    return facts


def _trim(facts: dict) -> None:
    """Keep the facts under ~12 KB by shortening the longest lists first."""
    for k in ("verification_queue", "landslide_roads", "closed_roads", "routes", "shelters", "clusters", "warnings"):
        while len(json.dumps(facts)) > MAX_FACTS_BYTES and len(facts.get(k, [])) > 3:
            facts[k] = facts[k][:-1]


def fact_index(facts: dict) -> dict[str, dict]:
    """id -> item for every id-bearing fact."""
    idx = {}
    for v in facts.values():
        if isinstance(v, list):
            for it in v:
                if isinstance(it, dict) and it.get("id"):
                    idx[it["id"]] = it
    return idx


_ID = re.compile(r"\b[A-Z]{1,2}\d+\b")
_NUM = re.compile(r"(?<![A-Za-z])-?\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    text = _ID.sub(" ", text)
    out = []
    for m in _NUM.findall(text):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def _fact_numbers(items: list[dict], facts: dict) -> list[float]:
    vals: list[float] = []

    def walk(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            vals.append(float(x))
        elif isinstance(x, str):
            vals.extend(_numbers(x))
        elif isinstance(x, dict):
            for k, v in x.items():
                if k not in ("lonlat",):
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for it in items:
        walk(it)
    walk(facts["scenario"])  # scenario numbers (hours, rain) may be cited with any id
    return vals


def _ok_number(n: float, vals: list[float]) -> bool:
    return any(abs(n - v) <= max(1.0, 0.01 * abs(v)) for v in vals)


def validate(recs: list[Recommendation], facts: dict) -> tuple[list[Recommendation], list[dict]]:
    """S15.3: drop recommendations citing unknown ids or numbers that are not in the cited facts."""
    idx = fact_index(facts)
    kept, dropped = [], []
    for r in recs:
        missing = [i for i in r.evidence_ids if i not in idx]
        if not r.evidence_ids or missing:
            dropped.append({"action": r.action, "reason": f"unknown evidence ids {missing or '(none)'}"})
            continue
        vals = _fact_numbers([idx[i] for i in r.evidence_ids], facts)
        bad = [n for n in _numbers(r.why) if not _ok_number(n, vals)]
        if bad:
            dropped.append({"action": r.action, "reason": f"numbers not in cited facts: {bad}"})
            log.info("advisory validator dropped %r: %s", r.action, bad)
            continue
        r.lonlat = next((idx[i]["lonlat"] for i in r.evidence_ids if idx[i].get("lonlat")), None)
        kept.append(r)
    return kept, dropped


def rules_advisory(facts: dict) -> list[Recommendation]:
    """S15.4: deterministic recommendations for all three horizons."""
    out: list[Recommendation] = []
    H = facts["scenario"]["H"]
    for b in facts["bridges"][:4]:
        h = b["first_closed_hour"]
        out.append(Recommendation(horizon="immediate", priority="P1",
                                  action=f"Close {b['name']} ({b['id']}) to traffic before hour {max(1, h - 1)}",
                                  location_label=b["name"], evidence_ids=[b["id"]],
                                  why=f"Estimated to close at hour {h} of {H} ({b['reason']}).", confidence="medium"))
    k = {x["id"]: x for x in facts["key_numbers"]}
    if k["K3"]["value"] > 0:
        out.append(Recommendation(horizon="immediate", priority="P1",
                                  action="Arrange external transport or additional shelter for people without a reachable place",
                                  location_label="Whole area", evidence_ids=["K3"],
                                  why=f"{k['K3']['value']} people have no reachable shelter place in this scenario.",
                                  confidence="medium"))
    by_cluster = defaultdict(list)
    for r in facts["routes"]:
        if r["from_cluster"]:
            by_cluster[r["from_cluster"]].append(r)
    for c in facts["clusters"][:3]:
        rts = by_cluster.get(c["id"])
        if rts:
            r = rts[0]
            out.append(Recommendation(horizon="immediate", priority="P1" if c["risk_class"] in ("critical", "high") else "P2",
                                      action=f"Evacuate {c['id']} to {r['to']} by the suggested route",
                                      location_label=f"Cluster {c['id']}", evidence_ids=[c["id"], r["id"]],
                                      why=f"{c['people']} people estimated exposed; route ETA {r['eta_min']} min.",
                                      confidence="medium"))
        else:
            out.append(Recommendation(horizon="immediate", priority="P2", action=f"Prepare to move residents of {c['id']}",
                                      location_label=f"Cluster {c['id']}", evidence_ids=[c["id"]],
                                      why=f"{c['people']} people estimated exposed, {c['risk_class']} risk.", confidence="low"))
    for g in facts["staging_points"][:2]:
        out.append(Recommendation(horizon="immediate", priority="P2", action=f"Pre-position ambulance and police at {g['id']}",
                                  location_label=f"Staging point {g['id']}", evidence_ids=[g["id"]],
                                  why="Dry, flat ground next to a road that stays open all scenario.", confidence="medium"))
    for d in facts["drains"][:3]:
        out.append(Recommendation(horizon="seasonal", priority="P2", action=f"Inspect and clear drain {d['id']} before monsoon",
                                  location_label=(d.get("name") or d.get("type", "drain")), evidence_ids=[d["id"]],
                                  why=f"Priority score {d.get('priority')}; {d.get('exposed_people_300m', 0)} exposed people within 300 m.",
                                  confidence="medium"))
    for L in facts["landslide_roads"][:3]:
        out.append(Recommendation(horizon="seasonal", priority="P2", action=f"Inspect slope protection on {L['name']}",
                                  location_label=L["name"], evidence_ids=[L["id"]],
                                  why=f"{L['length_km']} km reaches landslide class {L['lsi_max']} in this scenario.",
                                  confidence="low"))
    for s in [s for s in facts["shelters"] if s["assigned"] > 0][:3]:
        out.append(Recommendation(horizon="seasonal", priority="P2", action=f"Stock {s['name']} ({s['id']}) with supplies",
                                  location_label=s["name"], evidence_ids=[s["id"]],
                                  why=f"{s['assigned']} people assigned in this scenario.", confidence="medium"))
    for a in facts["assembly_points"][:2]:
        out.append(Recommendation(horizon="structural", priority="P3", action=f"Consider a permanent shelter near {a['id']}",
                                  location_label=f"Assembly point {a['id']}", evidence_ids=[a["id"]],
                                  why=f"Open high ground with room for {a['capacity']} people.", confidence="low"))
    if k["K3"]["value"] > 0 and facts["clusters"]:
        c = facts["clusters"][0]
        out.append(Recommendation(horizon="structural", priority="P3",
                                  action=f"Improve evacuation access and shelter capacity for {c['id']}",
                                  location_label=f"Cluster {c['id']}", evidence_ids=[c["id"], "K3"],
                                  why=f"{k['K3']['value']} people unplaced; {c['id']} has {c['people']} exposed.",
                                  confidence="low"))
    if not any(r.horizon == "seasonal" for r in out):
        out.append(Recommendation(horizon="seasonal", priority="P3", action="Verify the highest-ranked buildings in the field",
                                  location_label="Verification queue", evidence_ids=["K2"],
                                  why=f"{k['K2']['value']} buildings at high or critical estimated risk.", confidence="low"))
    if not any(r.horizon == "structural" for r in out):
        out.append(Recommendation(horizon="structural", priority="P3",
                                  action="Map schools and halls in OpenStreetMap and confirm shelter capacities",
                                  location_label="Whole area", evidence_ids=["K7"],
                                  why=f"{k['K7']['value']} people need to move in this scenario.", confidence="low"))
    return out


RULE_LIMITATIONS = [
    "Flood depths come from HAND mapping and rational-method runoff: uncalibrated, no channel routing, water never recedes.",
    "Landslide classes are susceptibility, not timed predictions; the rain trigger uses a published regional threshold.",
    "Building classes are proxies from footprints and heights until verified by field photos.",
    "Population is residential and night-time-like (WorldPop); daytime crowds may differ.",
    "Roads and shelters come from OpenStreetMap, which is incomplete in hill towns.",
]


def finalize(run_id: str, facts: dict, recs: list[Recommendation], headline: str, limitations: list[str],
             generated_by: str, dropped: list[dict] | None = None, model: str = "") -> Advisory:
    order = {"immediate": 0, "seasonal": 1, "structural": 2}
    recs = sorted(recs, key=lambda r: (order[r.horizon], r.priority))
    for i, r in enumerate(recs, start=1):
        r.id = f"R{i}"
    return Advisory(advisory_id=run_id, run_id=run_id, headline=headline,
                    key_numbers=[{"label": k["label"], "value": k["value"], "unit": k["unit"], "evidence_id": k["id"]}
                                 for k in facts["key_numbers"]],
                    recommendations=recs, limitations=(limitations or RULE_LIMITATIONS)[:5], disclaimer=DISCLAIMER,
                    generated_by=generated_by, dropped=dropped or [], model=model)
