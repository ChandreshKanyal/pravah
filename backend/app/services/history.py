"""S11 historical incidents: observed floods (Global Flood Database) and reported landslides (NASA GLC), kept separate
from modelled risk, plus grounded web leads from the historian agent.

Earth Engine data may be cached (GCS/Firestore); Maps geocodes for web leads are display-only and refreshed after 30 days.
"""
import logging
import time
from datetime import datetime, timezone

import ee
import numpy as np

from app.services import earth_engine as ees
from app.services import firestore as fs
from app.services import storage

log = logging.getLogger(__name__)
GFD_ID = "GLOBAL_FLOOD_DB/MODIS_EVENTS/V1"
INDIA_BBOX = [68.0, 6.5, 97.5, 37.5]
GEOCODE_MAX_AGE_S = 30 * 24 * 3600
_tiles: dict[str, tuple[float, str]] = {}


def gfd_tiles() -> str:
    """XYZ tile URL template for the 2000-2018 flood-count heat map (tokens expire; refreshed hourly)."""
    if "gfd" in _tiles and time.time() - _tiles["gfd"][0] < 3600:
        return _tiles["gfd"][1]
    ees.init_ee()
    col = ee.ImageCollection(GFD_ID)
    img = col.map(lambda i: i.select("flooded").And(i.select("jrc_perm_water").Not())).sum().selfMask()
    vis = {"min": 1, "max": 10, "palette": ["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26", "#a50f15"]}
    url = img.getMapId(vis)["tile_fetcher"].url_format
    _tiles["gfd"] = (time.time(), url)
    return url


def glc_india() -> list[dict]:
    """Reported landslides 1970-2019 in India's bounding box (cached in GCS: Earth Engine data)."""
    if storage.exists("_global", "glc_india.json"):
        return storage.get_json("_global", "glc_india.json")
    ees.init_ee()
    fc = ee.FeatureCollection(ees.LANDSLIDE_ID).filterBounds(ee.Geometry.Rectangle(INDIA_BBOX))
    keys = ["longitude", "latitude", "event_date", "fatality_c", "landslide_", "location_a"]
    d = ee.Dictionary({k: fc.aggregate_array(k) for k in keys}).getInfo()
    pts = [{"lon": lo, "lat": la, "date": (dt or "")[:10], "fatalities": fa or 0, "type": ty or "", "accuracy": ac or ""}
           for lo, la, dt, fa, ty, ac in zip(*(d[k] for k in keys)) if lo is not None and la is not None]
    storage.put_json("_global", "glc_india.json", pts)
    return pts


def _gfd_events(bbox) -> list[dict]:
    ees.init_ee()
    reg = ee.Geometry.Rectangle(list(bbox))

    def per_event(img):
        fl = img.select("flooded").And(img.select("jrc_perm_water").Not()).rename("f")
        st = fl.reduceRegion(ee.Reducer.sum(), reg, 250, maxPixels=1e8)
        return ee.Feature(None, {"pixels": st.get("f"), "start": img.date().format("YYYY-MM-dd"),
                                 "end": ee.Date(img.get("system:time_end")).format("YYYY-MM-dd"),
                                 "cause": img.get("dfo_main_cause"), "dead": img.get("dfo_dead"),
                                 "displaced": img.get("dfo_displaced"), "severity": img.get("dfo_severity"),
                                 "id": img.get("id")})
    fc = ee.FeatureCollection(ee.ImageCollection(GFD_ID).filterBounds(reg).map(per_event)).filter(ee.Filter.gt("pixels", 0))
    rows = [f["properties"] for f in fc.getInfo()["features"]]
    for r in rows:
        r["flooded_km2_in_area"] = round(float(r.pop("pixels")) * 0.0625, 2)  # 250 m pixels
    return sorted(rows, key=lambda r: r["start"], reverse=True)


def _glc_in(bbox) -> list[dict]:
    ees.init_ee()
    fc = ee.FeatureCollection(ees.LANDSLIDE_ID).filterBounds(ee.Geometry.Rectangle(list(bbox)))
    out = []
    for f in fc.getInfo()["features"]:
        p = f["properties"]
        out.append({"lon": p.get("longitude"), "lat": p.get("latitude"), "date": (p.get("event_date") or "")[:10],
                    "title": p.get("event_titl") or "", "type": p.get("landslide_") or "", "trigger": p.get("landslid_1") or "",
                    "fatalities": p.get("fatality_c"), "location_accuracy": p.get("location_a"),
                    "source_url": p.get("source_lin") or ""})
    return out


def _agreement(aoi_id: str) -> dict:
    """S11.5: share of historically flooded cells (GFD, 2000-2018) inside high flood susceptibility (FSI >= 0.6)."""
    hz = storage.load_layers(aoi_id, "hazard_hist")
    sus = storage.load_layers(aoi_id, "susceptibility")
    from app.engines.grid import rowcol_to_lonlat
    grid = storage.load_grid(aoi_id)
    w, s, e, n = (fs.get_aoi(aoi_id) or {})["bbox"]
    rr, cc = np.indices((grid.height, grid.width))
    lon, lat = rowcol_to_lonlat(grid, rr, cc)
    inside = (np.asarray(lon) >= w) & (np.asarray(lon) <= e) & (np.asarray(lat) >= s) & (np.asarray(lat) <= n)
    gfd_any = (np.nan_to_num(hz["gfd_count"]) > 0) & inside  # the grid includes a 3 km buffer; badge is AOI-only
    n = int(gfd_any.sum())
    if n == 0 or "fsi" not in sus:
        return {"agreement_pct": None, "gfd_cells": n}
    pct = 100.0 * float((gfd_any & (sus["fsi"] >= 0.6)).sum()) / n
    return {"agreement_pct": round(pct, 1), "gfd_cells": n,
            "note": "GFD flood counts are one of the FSI inputs, so agreement is partly built in."}


def aoi_history(aoi_id: str, fetch_web: bool = False, refresh: bool = False) -> dict:
    """Dataset incidents (cached per AOI in Firestore) and, if requested, grounded web leads."""
    doc = fs.get_doc("history_cache", aoi_id) or {}
    if refresh or "gfd_events" not in doc:
        aoi = fs.get_aoi(aoi_id) or {}
        bbox = aoi.get("bbox")
        if not bbox:
            raise KeyError(f"unknown AOI {aoi_id}")
        doc.update({"aoi_id": aoi_id, "gfd_events": _gfd_events(bbox), "landslides": _glc_in(bbox),
                    **_agreement(aoi_id), "datasets_at": datetime.now(timezone.utc).isoformat(),
                    "labels": {"gfd": "Observed floods 2000-2018 (Global Flood Database, MODIS 250 m)",
                               "glc": "Reported landslides 1970-2019 (NASA Global Landslide Catalog)"}})
        fs.set_doc("history_cache", aoi_id, doc)
    stale = time.time() - doc.get("web_at_ts", 0) > GEOCODE_MAX_AGE_S
    if fetch_web and (refresh or "web" not in doc or stale):
        from app.agents.historian import find_incidents
        aoi = fs.get_aoi(aoi_id) or {}
        web = find_incidents(aoi.get("name", ""), aoi.get("bbox"))
        doc.update({"web": web["incidents"], "web_sources": web["sources"], "search_entry_point": web["search_entry_point"],
                    "web_label": "From web sources, unverified leads", "web_at_ts": time.time()})
        fs.set_doc("history_cache", aoi_id, doc)
    return {k: v for k, v in doc.items() if k != "web_at_ts"}
