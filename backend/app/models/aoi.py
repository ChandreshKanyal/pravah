import hashlib
import math
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

MAX_KM = {"river": 15.0, "urban": 4.0}


class AOIValidationError(ValueError):
    pass


class AOIRequest(BaseModel):
    bbox: tuple[float, float, float, float]  # (west, south, east, north) WGS84
    name: str | None = None
    mode: Literal["river", "urban"] = "river"
    polygon_geojson: dict | None = None


class AOI(BaseModel):
    aoi_id: str  # sha1 of rounded bbox string, first 12 chars
    name: str  # user label or reverse-geocoded place
    bbox: tuple[float, float, float, float]  # (west, south, east, north) WGS84
    polygon_geojson: dict | None = None  # optional; bbox is the analysis extent
    mode: Literal["river", "urban"] = "river"  # river = HAND flood; urban = pluvial screening (S13)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def aoi_id_for(bbox: tuple[float, float, float, float]) -> str:
    w, s, e, n = bbox
    return hashlib.sha1(f"{w:.4f},{s:.4f},{e:.4f},{n:.4f}".encode()).hexdigest()[:12]


def bbox_size_km(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    """(width_km, height_km) using a local equirectangular approximation."""
    w, s, e, n = bbox
    lat_c = math.radians((s + n) / 2)
    return (e - w) * 111.32 * math.cos(lat_c), (n - s) * 110.57


def build_aoi(req: AOIRequest) -> AOI:
    w, s, e, n = req.bbox
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise AOIValidationError("bbox must be (west, south, east, north) with west < east and south < north")
    wkm, hkm = bbox_size_km(req.bbox)
    limit = MAX_KM[req.mode]
    if wkm > limit or hkm > limit:
        raise AOIValidationError(
            f"Area is {wkm:.1f} km x {hkm:.1f} km; {req.mode} mode allows at most {limit:.0f} km x {limit:.0f} km."
        )
    aoi_id = aoi_id_for(req.bbox)
    return AOI(
        aoi_id=aoi_id,
        name=req.name or f"Area {aoi_id}",
        bbox=req.bbox,
        polygon_geojson=req.polygon_geojson,
        mode=req.mode,
    )
