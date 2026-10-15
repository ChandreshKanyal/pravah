"""Forecast providers (S10.1-S10.4). Default: Google Maps Platform Weather API.

Weather API terms: responses are kept in memory for 10 minutes only, never persisted; runs store only the scenario
label and the series used. Attribution to Google is required wherever forecast data is shown.
Field names verified against https://weather.googleapis.com/$discovery/rest?version=v1 (16 Oct 2026):
precipitation.qpf.quantity (mm); hours pageSize is capped at 24, so we page; publicAlerts returns 404 for India.
"""
import time
from datetime import date
from functools import lru_cache
from typing import Protocol

import httpx

from app.config import get_settings

BASE = "https://weather.googleapis.com/v1"
TTL_S = 600
_cache: dict[tuple, tuple[float, object]] = {}


class ForecastProvider(Protocol):
    name: str

    def hourly(self, lat: float, lng: float, hours: int = 240) -> list[dict]: ...
    def daily(self, lat: float, lng: float, days: int = 10) -> list[dict]: ...
    def alerts(self, lat: float, lng: float) -> list: ...


@lru_cache
def maps_server_key() -> str:
    s = get_settings()
    if s.maps_server_key:
        return s.maps_server_key
    from google.cloud import secretmanager
    name = f"projects/{s.google_cloud_project}/secrets/maps-server-key/versions/latest"
    return secretmanager.SecretManagerServiceClient().access_secret_version(name=name).payload.data.decode()


def _cached(key: tuple, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < TTL_S:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def _qpf(precip: dict | None) -> float:
    return float(((precip or {}).get("qpf") or {}).get("quantity") or 0.0)


class GoogleWeatherProvider:
    name = "Google Maps Platform Weather API"

    def _get(self, path: str, params: dict, list_key: str, limit: int) -> list[dict]:
        out, token = [], None
        with httpx.Client(timeout=30) as c:
            while len(out) < limit:
                q = {**params, "key": maps_server_key()}
                if token:
                    q["pageToken"] = token
                r = c.get(f"{BASE}/{path}", params=q)
                if r.status_code == 404 and list_key == "weatherAlerts":
                    return []  # not supported for this location (e.g. India)
                r.raise_for_status()
                j = r.json()
                out += j.get(list_key, [])
                token = j.get("nextPageToken")
                if not token:
                    break
        return out[:limit]

    def hourly(self, lat: float, lng: float, hours: int = 240) -> list[dict]:
        def fetch():
            rows = self._get("forecast/hours:lookup", {"location.latitude": lat, "location.longitude": lng,
                                                       "hours": hours, "pageSize": 24}, "forecastHours", hours)
            out = []
            for h in rows:
                d = h.get("displayDateTime", {})
                out.append({"time": h["interval"]["startTime"],
                            "local_date": f"{d.get('year')}-{d.get('month'):02d}-{d.get('day'):02d}",
                            "local_hour": d.get("hours", 0), "precip_mm": _qpf(h.get("precipitation")),
                            "prob_pct": ((h.get("precipitation") or {}).get("probability") or {}).get("percent")})
            return out
        return _cached(("h", round(lat, 3), round(lng, 3), hours), fetch)

    def daily(self, lat: float, lng: float, days: int = 10) -> list[dict]:
        def fetch():
            rows = self._get("forecast/days:lookup", {"location.latitude": lat, "location.longitude": lng,
                                                      "days": days, "pageSize": days}, "forecastDays", days)
            out = []
            for d in rows:
                dd = d.get("displayDate", {})
                day_mm = _qpf((d.get("daytimeForecast") or {}).get("precipitation"))
                night_mm = _qpf((d.get("nighttimeForecast") or {}).get("precipitation"))
                out.append({"date": date(dd["year"], dd["month"], dd["day"]).isoformat(),
                            "precip_mm": round(day_mm + night_mm, 2)})
            return out
        return _cached(("d", round(lat, 3), round(lng, 3), days), fetch)

    def alerts(self, lat: float, lng: float) -> list:
        return _cached(("a", round(lat, 3), round(lng, 3)), lambda: self._get(
            "publicAlerts:lookup", {"location.latitude": lat, "location.longitude": lng}, "weatherAlerts", 50))


def get_provider() -> ForecastProvider:
    # S10.3 IMD provider is optional and not built (needs human-confirmed access); IMD is cited on Methods.
    return GoogleWeatherProvider()
