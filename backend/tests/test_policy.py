"""Tests for the policy-review changes (17 Oct): rounding, deadlines, place labels, supplies, bottom line, demand
breakdown and range, auth roles."""
import numpy as np
import pytest

from app.models.advisory import Recommendation
from app.pipeline import facts as F
from app.services import places


def _facts(win=4, start="2026-10-17T02:00", move=2295, gap=1367):
    return {"scenario": {"H": 6, "start_local": start, "move_before_hour": win, "move_before": F.deadline_text(win, start)},
            "key_numbers": [{"id": "K1", "value": 83, "unit": "people", "rounded": 85},
                            {"id": "K3", "value": gap, "unit": "people", "rounded": F.round_people(gap), "range": [900, 2100]},
                            {"id": "K4", "value": 3, "unit": "of 24 bridges"},
                            {"id": "K7", "value": move, "unit": "people", "rounded": F.round_people(move), "range": [1500, 3400]}],
            "clusters": [{"id": "C1", "place": "near Ratura (0.8 km NE)", "people": 113, "lonlat": [79.0, 30.3]},
                         {"id": "C2", "place": "Narkota", "people": 66, "lonlat": [79.0, 30.2]}],
            "bridges": [{"id": "B4", "name": "unnamed bridge", "place": "Tilwara", "first_closed_hour": 3, "lonlat": [79, 30]}],
            "routes": [{"id": "RT1", "from_place": "Narkota", "passable_until_h": None, "lonlat": [79, 30]}],
            "staging_points": [{"id": "G1", "place": "Rudraprayag", "lonlat": [79, 30]}], "breakdown": {}}


def test_round_people_removes_false_precision():
    assert [F.round_people(x) for x in (7, 83, 452, 2295, 10869)] == [5, 85, 450, 2300, 10900]


def test_clock_and_deadline_text():
    assert F.clock("2026-10-17T02:00", 4) == "05:00"
    assert F.clock("2026-10-17T22:00", 4) == "18 Oct 01:00"
    assert F.deadline_text(1, "2026-10-17T02:00") == "before the rain starts (02:00)"
    assert F.deadline_text(4, None) == "before hour 4"


def test_act_by_uses_first_closure_then_window():
    f = _facts()
    idx = F.fact_index(f)
    r_bridge = Recommendation(horizon="immediate", priority="P1", action="Close it", location_label="B4", evidence_ids=["B4"], why="", confidence="high")
    r_people = Recommendation(horizon="immediate", priority="P1", action="Move", location_label="Cluster C1", evidence_ids=["C1"], why="", confidence="high")
    r_stage = Recommendation(horizon="immediate", priority="P2", action="Stage", location_label="G1", evidence_ids=["G1"], why="", confidence="high")
    r_seas = Recommendation(horizon="seasonal", priority="P2", action="Clear", location_label="x", evidence_ids=["C1"], why="", confidence="low")
    assert F._act_by(r_bridge, idx, f) == (3, "before hour 3 (04:00)")
    assert F._act_by(r_people, idx, f) == (4, "before hour 4 (05:00)")
    assert F._act_by(r_stage, idx, f)[0] == 1
    assert F._act_by(r_seas, idx, f) == (None, "before the monsoon")


def test_labels_replace_bare_ids_with_place_names():
    idx = F.fact_index(_facts())
    r = Recommendation(horizon="immediate", priority="P1", action="x", location_label="Cluster C1 and Cluster C2",
                       evidence_ids=["C1", "C2"], why="", confidence="high")
    assert F._label(r, idx) == "near Ratura (0.8 km NE), Narkota"
    r.location_label = "Rudraprayag bypass"
    assert F._label(r, idx) == "Rudraprayag bypass"


def test_bottom_line_says_who_where_when_gap():
    t = F.bottom_line(_facts())
    assert t.startswith("Move about 2,300 people (1,500 to 3,400) from Ratura, Narkota before hour 4 (05:00)")
    assert "about 1,350 have no reachable shelter place" in t
    assert F.bottom_line(_facts(move=0)).startswith("No evacuation is needed")


def test_supplies_follow_sphere_minimums():
    s = {x["item"]: x for x in F.supplies(100, 150, days=3)}
    assert s["Drinking and domestic water"]["quantity"] == 4500 and s["Drinking and domestic water"]["quantity_high"] == 6750
    assert s["Latrines"]["quantity"] == 5 and s["Hygiene kits"]["quantity"] == 20


def test_validator_ignores_clock_times():
    assert F._numbers("before hour 4 (05:00), 113 people") == [4.0, 113.0]


def test_place_label_prefers_bigger_places_and_reports_direction():
    pl = [{"name": "Rudraprayag", "name_hi": "रुद्रप्रयाग", "kind": "town", "lon": 78.98, "lat": 30.285},
          {"name": "Tiny", "name_hi": "", "kind": "hamlet", "lon": 78.9905, "lat": 30.285}]
    assert places.label(pl, 78.98, 30.2852) == "Rudraprayag"
    assert places.label(pl, 78.98, 30.285, hindi=True) == "रुद्रप्रयाग"
    lab = places.label(pl, 79.0, 30.285)  # 0.9 km east of Tiny, 1.9 km east of the town
    assert lab.startswith("near ") and lab.endswith(" E)")
    assert places.label(pl, 79.2, 30.5) == ""


def test_demand_breakdown_and_range():
    from app.pipeline.evac import _demand_breakdown
    ctx = {"pop_b": np.array([10.0, 20.0, 30.0]), "pop_un": np.zeros((2, 2)),
           "d_b": np.array([[0.4, 0.0, 0.06]]), "ls_b": np.array([[1, 5, 5]])}
    out = _demand_breakdown(ctx, np.zeros((1, 2, 2)), None, 0.05, 0.05, 5)
    assert out["flood"] == 10 and out["landslide"] == 20 and out["both"] == 30 and out["central"] == 60
    # depth x0.7: 0.06 -> 0.042 is dry, but that building is still on a class-5 slope, so the low count is 60 x 0.8
    assert out["low"] == pytest.approx(48.0) and out["high"] == pytest.approx(72.0)


def test_roles_and_auth_required(monkeypatch):
    from fastapi import HTTPException
    from app import auth
    from app.config import get_settings
    anon = {"email": "", "name": "", "role": "viewer", "verified": False}
    with pytest.raises(HTTPException) as e:
        auth.require("analyst")(anon)
    assert e.value.status_code == 403
    monkeypatch.setattr(get_settings(), "auth_required", True)
    with pytest.raises(HTTPException) as e:
        auth.require("viewer")({**anon, "role": "admin"})
    assert e.value.status_code == 401
    assert auth.require("approver")({"email": "a", "name": "A", "role": "admin", "verified": True})["name"] == "A"
