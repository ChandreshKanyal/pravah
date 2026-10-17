"""AI emulator of the 2D flow model per area (pipeline/emulator.py): training, instant what-if maps, rain triggers."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.auth import require
from app.engines.render import DEPTH_COLORS, DEPTH_EDGES, overlay_payload, to_png_binned
from app.pipeline import emulator
from app.services import firestore as fs, storage

router = APIRouter()
Shape = Literal["constant", "triangular_front"]


@router.get("/api/aoi/{aoi_id}/emulator")
def emulator_status(aoi_id: str):
    """{state: none | queued | running | ready | failed, progress, validation (leave-one-out), range, ...}."""
    st = emulator.status(aoi_id)
    if st.get("state") == "ready":
        st["overlay"] = overlay_payload(storage.load_grid(aoi_id))
    return st


@router.get("/api/aoi/{aoi_id}/emulator/meta")
def emulator_meta(aoi_id: str):
    """Full training record: design storms and per-run leave-one-out scores (Methods page)."""
    m = emulator.meta_json(aoi_id)
    if not m:
        raise HTTPException(404, "No emulator for this area yet")
    return m


@router.post("/api/aoi/{aoi_id}/emulator")
def emulator_train(aoi_id: str, force: bool = False, user: dict = Depends(require("analyst"))):
    if not fs.get_aoi(aoi_id):
        raise HTTPException(404, "Unknown AOI")
    return emulator.start(aoi_id, force)


def _q(total_mm: float = Query(..., ge=0, le=1000), hours: int = Query(..., ge=1, le=24),
       shape: Shape = "triangular_front", river_offset_m: float = Query(0.0, ge=-1, le=5)):
    return total_mm, hours, shape, river_offset_m


@router.get("/api/aoi/{aoi_id}/emulator/predict")
def emulator_predict(aoi_id: str, q=Depends(_q)):
    """Instant estimate of the 2D model's peak flood for a storm: flooded area, deepest water, people in water at least
    30 cm deep, the IMD category of the storm, and whether it lies outside the trained range."""
    h, stats = emulator.predict(aoi_id, *q)
    if h is None:
        raise HTTPException(409, "The emulator for this area is not trained yet")
    return stats


@router.get("/api/aoi/{aoi_id}/emulator/predict.png")
def emulator_png(aoi_id: str, q=Depends(_q)):
    h, _ = emulator.predict(aoi_id, *q)
    if h is None:
        raise HTTPException(409, "The emulator for this area is not trained yet")
    return Response(to_png_binned(h, DEPTH_EDGES, DEPTH_COLORS), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/api/aoi/{aoi_id}/triggers")
def area_triggers(aoi_id: str):
    """Anticipatory-action rain triggers per settlement (mm in 1, 3, 6 h and the matching IMD category)."""
    t = emulator.triggers_json(aoi_id)
    if not t:
        raise HTTPException(404, "No triggers yet: the emulator for this area is not trained")
    return t
