"""Historical event replays (policy review, 17 Oct): run the model with the observed rain of known disasters and report
what it would have said, next to what was recorded. Honest evidence, not validation:

- rain is NASA IMERG V07 (satellite, ~10 km, under-reads convective cores);
- landslide records are NASA GLC points with 5-10 km location accuracy, so only the rain trigger can be tested, not
  the exact slope;
- no observed flood extent exists inside either box (the Global Flood Database has no pixels there).

The seasonal check counts how many days of the same monsoon would also have crossed the daily trigger (false alarms).
Results go to aois/{id}.meta.event_replays for the Methods page.

    backend/.venv/bin/python scripts/event_replay.py [aoi_id ...]
"""
import io
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import numpy as np  # noqa: E402

EVENTS = {
    "56f044f26351": [  # Rudraprayag
        {"id": "2012-09-14", "label": "Ukhimath and Rudraprayag cloudburst, night of 13-14 Sep 2012",
         "record": "NASA GLC: landslide, 19 deaths, 'Rudraprayag, Uttarakhand' (5 km accuracy)", "start": "2012-09-13T00:00:00",
         "glc_date": "09/14/2012"},
        {"id": "2010-09-03", "label": "Rishikesh-Badrinath highway landslide at Rudraprayag, 3 Sep 2010",
         "record": "NASA GLC: landslide, 8,000 pilgrims stranded (10 km accuracy)", "start": "2010-09-02T00:00:00",
         "glc_date": "09/03/2010"},
        {"id": "2013-06-16", "label": "Kedarnath disaster, 16-17 Jun 2013",
         "record": "Mandakini and Alaknanda floods; no point record inside this box", "start": "2013-06-15T12:00:00"},
    ],
    "d277268c1783": [  # Mumbai Kurla-Mithi
        {"id": "2005-07-26", "label": "Mumbai deluge, 26 Jul 2005",
         "record": "IMD Santacruz gauge 944 mm in 24 h; Kurla among the worst-flooded areas (Mithi overflow)", "start": "2005-07-26T00:00:00"},
        {"id": "2017-08-29", "label": "Mumbai floods, 29 Aug 2017",
         "record": "IMD Santacruz about 330 mm in 12 h; widespread waterlogging", "start": "2017-08-29T00:00:00"},
    ],
}
H = 12  # replay the wettest 12 hours of the 48-hour window


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    from datetime import date
    from app.engines import rainfall
    from app.engines.grid import lonlat_to_rowcol
    from app.models.scenario import ScenarioParams
    from app.pipeline.run_pipeline import area_centroid, load_area, run_pipeline
    from app.services import earth_engine as ees, firestore as fs, storage

    for aoi_id in sys.argv[1:] or list(EVENTS):
        area = load_area(aoi_id)
        lon, lat = area_centroid(area)
        thr = rainfall.threshold_name("auto", lon, lat)
        day_thr = float(rainfall.landslide_threshold([24], thr)[0]) * 24  # mm in 24 h on the I-D curve
        out = []
        for ev in EVENTS.get(aoi_id, []):
            rain48 = ees.imerg_hourly(lon, lat, ev["start"], 48)
            win, k = rainfall.wettest_window(rain48, H)
            run = run_pipeline(ScenarioParams(aoi_id=aoi_id, rain_source="manual", duration_h=H, rain_series_override=win,
                                              preset_label=f"Replay: {ev['label']} (IMERG, wettest {H} h = {sum(win):.0f} mm)"))
            m = run.methods or {}
            res = {"id": ev["id"], "label": ev["label"], "record": ev["record"], "run_id": run.run_id,
                   "imerg_48h_mm": round(sum(rain48), 1), "imerg_peak_mm_h": round(max(rain48), 1),
                   "window_mm": round(sum(win), 1), "window_start_utc_hour": int(k),
                   "trigger": thr, "trigger_ratio_max": m.get("landslide_exceedance_max"),
                   "trigger_fired": bool(m.get("landslide_trigger_hours")), "trigger_hours": m.get("landslide_trigger_hours", []),
                   "people_to_move": run.people_to_evacuate, "demand_breakdown": run.demand_breakdown,
                   "flooded_km2": run.flooded_area_km2_by_hour[-1], "flood_peak_people": max(run.exposure.exposed_pop_by_hour or [0])}
            if ev.get("glc_date"):  # landslide classes around the catalogue point (its accuracy is 5-10 km)
                doc = fs.get_doc("history_cache", aoi_id) or {}
                pts = [x for x in doc.get("landslides", []) if x.get("date") == ev["glc_date"]]
                try:
                    lsi = np.load(io.BytesIO(storage.get_run(run.run_id, "lsi.npz")))["lsi_dyn_class"].max(axis=0)
                except Exception:
                    lsi = None
                if pts and lsi is not None:
                    r, c = (int(v) for v in lonlat_to_rowcol(area.grid, pts[0]["lon"], pts[0]["lat"]))
                    rad = int(1000 / area.grid.cell)
                    win_cls = lsi[max(0, r - rad): r + rad + 1, max(0, c - rad): c + rad + 1]
                    res["glc_point_class"] = int(lsi[r, c]) if 0 <= r < lsi.shape[0] and 0 <= c < lsi.shape[1] else None
                    res["share_class4plus_within_1km"] = round(float((win_cls >= 4).mean()), 3)
                    res["share_class4plus_area"] = round(float((lsi[area.aoi_mask] >= 4).mean()), 3)
            # season context: days of that monsoon (Jun-Sep) whose IMERG total crosses the 24 h trigger
            y = int(ev["id"][:4])
            season = [d for d in ees.imerg_daily(lon, lat, date(y, 10, 1), 122) if d["precip_mm"] is not None]
            over = [d for d in season if d["precip_mm"] >= day_thr]
            ev_day = max((d for d in season if d["date"] in (ev["id"], ev["start"][:10])), key=lambda d: d["precip_mm"], default=None)
            res["season"] = {"days": len(season), "days_over_24h_trigger": len(over), "trigger_24h_mm": round(day_thr, 1),
                             "event_day_mm": ev_day["precip_mm"] if ev_day else None,
                             "event_day_rank": (1 + sum(1 for d in season if ev_day and d["precip_mm"] > ev_day["precip_mm"])) if ev_day else None}
            out.append(res)
            print(json.dumps(res, indent=1))
        doc = fs.get_aoi(aoi_id) or {}
        meta = doc.get("meta", {})
        meta["event_replays"] = out
        fs.update_aoi(aoi_id, {"meta": meta})


if __name__ == "__main__":
    main()
