from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.engines import rainfall
from app.models.scenario import ScenarioParams
from app.pipeline.run_pipeline import AreaNotReady, area_centroid, load_area, screening
from app.services import earth_engine as ees
from app.services.weather import get_provider

router = APIRouter()
_past: dict[tuple, list] = {}


@router.get("/api/forecast")
def forecast(aoi_id: str, duration_h: int = Query(4, ge=1, le=24)):
    """S10.8: hourly (240 h) + daily (10 d) rain, alerts, worst day, past 90 days, 10-day screening strip."""
    try:
        area = load_area(aoi_id)
    except AreaNotReady as e:
        raise HTTPException(409, str(e))
    lon, lat = area_centroid(area)
    prov = get_provider()
    warnings = []
    try:
        hourly, daily = prov.hourly(lat, lon, 240), prov.daily(lat, lon, 10)
        alerts = prov.alerts(lat, lon)
    except Exception as e:
        hourly, daily, alerts = [], [], []
        warnings.append(f"Forecast provider unavailable: {e.__class__.__name__}")
    key = (aoi_id, date.today().isoformat())
    if key not in _past:  # Earth Engine (not Maps) data: safe to keep for the day
        try:
            _past[key] = ees.imerg_daily(lon, lat, date.today(), 90)
        except Exception as e:
            warnings.append(f"Past-90-day rainfall unavailable: {e.__class__.__name__}")
    return {
        "hourly": hourly, "daily": daily, "alerts": alerts,
        "worst_day_index": rainfall.worst_day_index(daily, hourly),
        "past_90d": _past.get(key, []),
        "screening": screening(area, daily, hourly, duration_h) if daily else [],
        "screening_note": "Screening only (one reach); run the full scenario for details.",
        "provider": prov.name, "attribution": "Forecast data: Google Maps Platform Weather API",
        "past_90d_source": "NASA GPM IMERG V07 via Earth Engine", "warnings": warnings,
    }


@router.post("/api/aoi/{aoi_id}/rain-hours")
def rain_hours(aoi_id: str, params: ScenarioParams):
    """The exact hourly rain (mm in each hour) a scenario would use, from the run's own rain builder (forecast, worst,
    record, observed past day, IMD presets, custom), so the Scenario panel shows it and staff can edit it hour by hour."""
    from app.pipeline.run_pipeline import rain_series
    try:
        area = load_area(aoi_id)
    except AreaNotReady as e:
        raise HTTPException(409, str(e))
    p = params.model_copy(update={"aoi_id": aoi_id, "rain_series_override": None})
    try:
        series, label, warnings, start = rain_series(p, area)
    except Exception as e:  # observed rain needs Earth Engine
        raise HTTPException(502, f"Rain unavailable: {e.__class__.__name__}")
    return {"series": [round(float(x), 1) for x in series], "label": label, "start_local": start, "warnings": warnings}
