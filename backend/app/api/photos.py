"""S12 field photo verification: authorities upload their own photos; Gemini vision classifies the structure or drain;
the result is linked to the nearest building (20 m) or waterway (30 m) and overrides the proxy class on the next run.
No Maps imagery is ever used."""
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from google.genai import types
from PIL import ExifTags, Image

from app.models.photo import PHOTO_TO_BUILDING, BuildingPhotoResult, DrainPhotoResult
from app.services import firestore as fs
from app.services import gemini, storage

router = APIRouter()
log = logging.getLogger(__name__)
MAX_BYTES = 12 * 1024 * 1024
MIN_OVERRIDE_CONFIDENCE = 0.6

PROMPT = ("You are assisting a disaster-management engineer with a rapid visual survey. Look only at the structure "
          "(or drain) in this photo. Classify it using the schema. If the view is unclear, use \"unclear\" and a low "
          "confidence. Do not describe or infer anything about people. This is a first-pass triage for field "
          "verification, not a structural assessment.")


def exif_lonlat(img: Image.Image) -> tuple[float, float] | None:
    """(lon, lat) from EXIF GPS, or None."""
    try:
        gps = img.getexif().get_ifd(ExifTags.IFD.GPSInfo)
        if not gps:
            return None

        def deg(v, ref):
            d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
            return -d if ref in ("S", "W") else d
        return deg(gps[4], gps[3]), deg(gps[2], gps[1])
    except Exception:
        return None


def _jpeg(img: Image.Image) -> bytes:
    """Re-encode as JPEG without EXIF (strips camera metadata), longest side <= 1600 px."""
    img = img.convert("RGB")
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _link(aoi_id: str, kind: str, lon: float, lat: float) -> dict:
    import geopandas as gpd
    from shapely.geometry import Point
    if kind == "building":
        name, max_m, key = "buildings_proxy.parquet", 20.0, "bid"
    else:
        name, max_m, key = "waterways.parquet", 30.0, "osmid"
    if not storage.exists(aoi_id, name):
        return {}
    g = storage.load_gdf(aoi_id, name)
    crs = storage.load_grid(aoi_id).crs
    g = g.to_crs(crs) if g.crs and g.crs.to_string() != crs else g
    pt = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326").to_crs(crs).iloc[0]
    d = g.geometry.distance(pt)
    i = int(d.idxmin()) if len(d) else None
    if i is None or float(d.loc[i]) > max_m:
        return {"link_distance_m": round(float(d.min()), 1) if len(d) else None}
    row = g.loc[i]
    out = {"link_distance_m": round(float(d.loc[i]), 1)}
    if kind == "building":
        out.update(linked_bid=str(row["bid"]), previous_class=str(row.get("structure_class", "")))
    else:
        out.update(linked_drain_id=str(row.get(key, i)), drain_type=str(row.get("waterway", "")))
    return out


def classify(data: bytes, kind: str):
    schema = BuildingPhotoResult if kind == "building" else DrainPhotoResult
    part = types.Part.from_bytes(data=data, mime_type="image/jpeg")
    return gemini.generate_json([part, PROMPT], schema, tier="fast", temperature=0.1)


@router.post("/api/photos")
async def upload_photo(file: UploadFile = File(...), aoi_id: str = Form(...),
                       kind: Literal["building", "drain"] = Form("building"),
                       lat: float | None = Form(None), lng: float | None = Form(None)):
    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "Photo larger than 12 MB")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        raise HTTPException(400, "Not a readable image")
    gps = exif_lonlat(img)
    if gps is None and (lat is None or lng is None):
        raise HTTPException(422, "No GPS in the photo: drop a pin on the map to give its location")
    lon_, lat_ = (lng, lat) if lat is not None and lng is not None else gps
    jpg = _jpeg(img)
    photo_id = uuid.uuid4().hex[:12]
    await run_in_threadpool(storage.put_bytes, aoi_id, f"photos/{photo_id}.jpg", jpg, "image/jpeg")
    try:
        result = await run_in_threadpool(classify, jpg, kind)
    except Exception as e:
        log.exception("photo classification failed")
        raise HTTPException(502, f"Classification unavailable ({e.__class__.__name__})")
    res = result.model_dump()
    visible = res["building_visible"] if kind == "building" else res["drain_visible"]
    doc = {"photo_id": photo_id, "aoi_id": aoi_id, "kind": kind, "lon": lon_, "lat": lat_,
           "location_source": "exif" if gps and lat is None else "pin", "result": res, "model": gemini.model_name("fast"),
           "created_at": datetime.now(timezone.utc).isoformat(), "accepted": False, "message": ""}
    if not visible:
        doc["message"] = f"No {kind} clearly visible in this photo; not applied. Try a clearer, closer shot."
    else:
        doc.update(await run_in_threadpool(_link, aoi_id, kind, lon_, lat_))
        linked = doc.get("linked_bid") or doc.get("linked_drain_id")
        cls = res.get("structure_class") if kind == "building" else res.get("condition")
        if not linked:
            doc["message"] = f"No mapped {kind} within {20 if kind == 'building' else 30} m of this location; saved but not linked."
        elif cls == "unclear" or res["confidence"] < MIN_OVERRIDE_CONFIDENCE:
            doc["message"] = f"Low confidence ({res['confidence']:.2f}) or unclear; saved for review, not applied."
        else:
            doc["accepted"] = True
            if kind == "building":
                doc["override_class"] = PHOTO_TO_BUILDING[cls]
                doc["message"] = (f"Building {linked} reclassified from {doc.get('previous_class', 'proxy')} to "
                                  f"{PHOTO_TO_BUILDING[cls]}. Applied on the next run.")
            else:
                doc["message"] = f"Drain {linked} marked {cls}. Applied on the next run (urban drain priority)."
    fs.set_doc("photos", photo_id, doc)
    return doc


@router.get("/api/photos")
def list_photos(aoi_id: str):
    docs = fs.query("photos", aoi_id=aoi_id)
    return sorted(docs, key=lambda d: d.get("created_at", ""), reverse=True)


@router.get("/api/photos/{photo_id}.jpg")
def photo_image(photo_id: str, aoi_id: str):
    from fastapi.responses import Response
    if not storage.exists(aoi_id, f"photos/{photo_id}.jpg"):
        raise HTTPException(404, "Unknown photo")
    return Response(storage.get_bytes(aoi_id, f"photos/{photo_id}.jpg"), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600"})


def building_overrides(aoi_id: str) -> dict[str, dict]:
    """bid -> {class, confidence} for accepted building photos (latest wins). Read by run_pipeline (S6.3)."""
    out: dict[str, dict] = {}
    try:
        docs = sorted(fs.query("photos", aoi_id=aoi_id, kind="building", accepted=True), key=lambda d: d.get("created_at", ""))
    except Exception as e:
        log.info("photo overrides unavailable: %s", e)
        return out
    for d in docs:
        out[d["linked_bid"]] = {"class": d["override_class"], "confidence": d["result"]["confidence"], "photo_id": d["photo_id"]}
    return out
