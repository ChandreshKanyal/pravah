"""S18.1: prepare the demo areas ahead of time so the live demo reads from cache, then run a default scenario and
generate its advisory. Usage (from repo root):

    backend/.venv/bin/python scripts/preprocess_demo_aoi.py [rudraprayag|mumbai|all] [--force step,step]
"""
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.aoi import AOIRequest, build_aoi  # noqa: E402
from app.services import firestore as fs  # noqa: E402

DEMOS = {
    "rudraprayag": {"bbox": (78.93, 30.24, 79.03, 30.33), "name": "Rudraprayag 10km", "mode": "river",
                    "run": {"rain_source": "historical_extreme", "duration_h": 4}},
    "mumbai": {"bbox": (72.865, 19.06, 72.895, 19.09), "name": "Mumbai Kurla-Mithi", "mode": "urban",
               "run": {"rain_source": "manual", "manual_intensity_mm_h": 60, "duration_h": 3, "hyetograph": "triangular_front"}},
}


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    which = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "all"
    force = frozenset(sys.argv[sys.argv.index("--force") + 1].split(",")) if "--force" in sys.argv else frozenset()
    from app.agents.advisor import generate_advisory
    from app.api.runs import area_extra
    from app.models.scenario import ScenarioParams
    from app.pipeline.prepare_area import prepare_area
    from app.pipeline.run_pipeline import run_pipeline
    for key, d in DEMOS.items():
        if which not in ("all", key):
            continue
        aoi = build_aoi(AOIRequest(bbox=d["bbox"], name=d["name"], mode=d["mode"]))
        if not fs.get_aoi(aoi.aoi_id):
            fs.set_aoi(aoi.aoi_id, {**aoi.model_dump(mode="json"), "state": "queued", "status": {}})
        t = time.time()
        r = prepare_area(aoi, force)
        print(f"{key}: aoi_id={aoi.aoi_id} state={r['state']} in {time.time() - t:.0f}s")
        for w in r["warnings"]:
            print("   note:", w)
        if r["state"] not in ("ready", "partial"):
            continue
        t = time.time()
        run = run_pipeline(ScenarioParams(aoi_id=aoi.aoi_id, **d["run"])).model_dump(mode="json")
        print(f"   run {run['run_id']} in {time.time() - t:.1f}s: {run['rain_label']} | to move {run['people_to_evacuate']}, "
              f"gap {run['capacity_gap_people']}, flooded {run['flooded_area_km2_by_hour'][-1]} km2, drains {len(run.get('drains', []))}")
        adv = generate_advisory(run, area_extra(aoi.aoi_id, run["run_id"]))
        fs.set_doc("advisories", run["run_id"], {**adv.model_dump(mode="json"), "status": "ready"})
        print(f"   advisory: {adv.generated_by}, {len(adv.recommendations)} recommendations")
        print(json.dumps({"aoi_id": aoi.aoi_id, "run_id": run["run_id"]}))


if __name__ == "__main__":
    main()
