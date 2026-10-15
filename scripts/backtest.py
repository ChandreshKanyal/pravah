"""S18.2 backtest (honest evidence, not validation): overlap of a heavy-rain scenario's modelled flood with Global Flood
Database (MODIS, 2000-2018) flooded pixels inside the AOI. MODIS is 250 m and the event rain is unknown, so this is a
sanity check only. Results go to aois/{id}.meta.backtest for the Methods page.

    backend/.venv/bin/python scripts/backtest.py <aoi_id> [manual_mm_h=100] [hours=6] [upstream_inflow_m3s=0]
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import numpy as np  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    from app.engines.grid import rowcol_to_lonlat
    from app.models.scenario import ScenarioParams
    from app.pipeline.run_pipeline import run_pipeline
    from app.services import firestore as fs, storage

    aoi_id = sys.argv[1]
    mm = float(sys.argv[2]) if len(sys.argv) > 2 else 100.0
    hours = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    inflow = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
    doc = fs.get_aoi(aoi_id)
    w, s, e, n = doc["bbox"]
    grid = storage.load_grid(aoi_id)
    rr, cc = np.indices((grid.height, grid.width))
    lon, lat = (np.asarray(x) for x in rowcol_to_lonlat(grid, rr, cc))
    inside = (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)
    gfd = (np.nan_to_num(storage.load_layers(aoi_id, "hazard_hist")["gfd_count"]) > 0) & inside
    run = run_pipeline(ScenarioParams(aoi_id=aoi_id, rain_source="manual", manual_intensity_mm_h=mm, duration_h=hours,
                                      upstream_inflow_m3s=inflow))
    depth = np.load(__import__("io").BytesIO(storage.get_run(run.run_id, "depth.npz")))["depth"].astype(np.float32)
    model = (np.nan_to_num(depth[-1]) >= 0.05) & inside
    hit = int((gfd & model).sum())
    res = {"run_id": run.run_id, "scenario": run.rain_label, "upstream_inflow_m3s": inflow,
           "gfd_cells": int(gfd.sum()), "model_wet_cells": int(model.sum()), "overlap_cells": hit,
           "note": "MODIS 250 m vs 30 m model; event rain unknown; sanity check, not validation"}
    if gfd.sum() == 0:
        res["result"] = "No Global Flood Database flood pixels inside this area (2000-2018); no overlap test possible."
    else:
        res.update(pod=round(hit / gfd.sum(), 3), far=round(1 - hit / max(model.sum(), 1), 3),
                   csi=round(hit / max(int((gfd | model).sum()), 1), 3))
        res["result"] = (f"{res['pod']:.0%} of observed flood pixels are wet in the model (POD); CSI {res['csi']:.2f}; "
                         f"{res['far']:.0%} of modelled wet cells were never observed flooded (expected: the scenario is "
                         "extreme and MODIS misses narrow or short floods).")
    meta = doc.get("meta", {})
    meta["backtest"] = res
    fs.update_aoi(aoi_id, {"meta": meta})
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
