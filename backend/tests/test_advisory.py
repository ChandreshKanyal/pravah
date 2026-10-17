"""S15 acceptance: the validator drops unknown ids and invented numbers; a Gemini error yields rules_fallback with
all three horizons."""
from unittest import mock

import pytest

from app.models.advisory import DISCLAIMER, Recommendation
from app.pipeline import facts as F


def _run():
    return {
        "run_id": "r1", "aoi_id": "a1", "rain_label": "Manual 60 mm/h for 4 h", "rain_series_mm_h": [60, 60, 60, 60],
        "flooded_area_km2_by_hour": [0.2, 0.4, 0.5, 0.66], "capacity_gap_people": 120, "people_to_evacuate": 900,
        "exposure": {"exposed_pop_by_hour": [10, 50, 200, 251],
                     "buildings_by_risk": {"critical": 2, "high": 40},
                     "clusters": [{"id": "C1", "people": 300, "max_depth": 1.2, "risk_class": "high",
                                   "dominant_class": "informal_cluster", "centroid": [79.0, 30.3]}]},
        "shelters": [{"id": "S1", "name": "Hall", "kind": "community_centre", "capacity": 500, "assigned": 480, "spare": 20,
                      "status": "usable", "lon": 79.01, "lat": 30.29}],
        "bridges": [{"id": "B1", "name": "Old bridge", "first_closed_hour": 3, "reason": "bridge", "lon": 79.0, "lat": 30.3}],
        "routes": [{"from_node": 1, "from_lon": 79.0001, "from_lat": 30.3001, "to_shelter": "S1", "people": 480,
                    "eta_min": 18.5, "passable_until_h": 3, "use_now_gone_soon": False}],
        "assembly_points": [{"id": "A1", "capacity": 2000, "area_m2": 8000, "lon": 79.02, "lat": 30.28}],
        "staging_points": [{"id": "G1", "near_cluster": "C1", "lon": 79.005, "lat": 30.295}],
        "hotspots": [], "warnings": [], "methods": {},
    }


@pytest.fixture(autouse=True)
def no_gcs():
    with mock.patch.object(F, "load_roads", return_value={"features": []}):
        yield


def test_validator_drops_unknown_id_and_invented_numbers():
    facts = F.build_facts(_run())
    recs = [
        Recommendation(horizon="immediate", priority="P1", action="Open S99", location_label="x", evidence_ids=["S99"],
                       why="S99 has room for 500.", confidence="high"),
        Recommendation(horizon="immediate", priority="P1", action="Fill S1", location_label="x", evidence_ids=["S1"],
                       why="S1 has 700 spare places.", confidence="high"),
        Recommendation(horizon="immediate", priority="P1", action="Close B1", location_label="x", evidence_ids=["B1"],
                       why="B1 is estimated to close at hour 3 of 4.", confidence="high"),
    ]
    kept, dropped = F.validate(recs, facts)
    assert [r.action for r in kept] == ["Close B1"]
    assert kept[0].lonlat == [79.0, 30.3]
    assert "S99" in dropped[0]["reason"] and "700" in dropped[1]["reason"]


def test_gemini_error_gives_rules_fallback_with_three_horizons():
    from app.agents import advisor
    with mock.patch.object(advisor.gemini, "generate_json", side_effect=RuntimeError("boom")):
        adv = advisor.generate_advisory(_run(), {})
    assert adv.generated_by == "rules_fallback"
    assert {r.horizon for r in adv.recommendations} == {"immediate", "seasonal", "structural"}
    assert adv.disclaimer == DISCLAIMER
    assert all(r.id.startswith("R") for r in adv.recommendations)
    assert any("B1" in r.evidence_ids for r in adv.recommendations)


def test_route_linked_to_nearest_cluster():
    facts = F.build_facts(_run())
    assert facts["routes"][0]["from_cluster"] == "C1"
