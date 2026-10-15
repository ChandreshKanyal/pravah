from enum import Enum
from typing import Literal

from pydantic import BaseModel


class RainSource(str, Enum):
    forecast = "forecast"
    worst = "worst"
    best = "best"
    historical_extreme = "historical_extreme"
    manual = "manual"


class ScenarioParams(BaseModel):
    aoi_id: str
    rain_source: RainSource = RainSource.forecast
    forecast_day_index: int | None = None  # 0..9; None = auto-pick worst day
    manual_intensity_mm_h: float = 50.0  # for manual
    duration_h: int = 4  # 1..24 hours simulated
    hyetograph: Literal["constant", "triangular_front"] = "constant"
    worst_multiplier: float = 1.5  # worst = forecast x this
    best_multiplier: float = 0.5
    river_offset_m: float = 0.0  # added to every reach stage (pre-existing high water)
    manning_n: float = 0.04
    pop_multiplier: float = 1.0
    pop_total_override: int | None = None
    disabled_shelter_ids: list[str] = []
    extra_shelters: list[dict] = []  # {id,name,lat,lng,capacity}
    blocked_polygons: list[dict] = []  # GeoJSON polygons drawn by user
    travel_mode: Literal["walk", "drive"] = "walk"
    evac_start_hour: int = 1  # decision hour for routing
    vehicle_depth_limit_m: float = 0.3
    walk_depth_limit_m: float = 0.5
    bridge_cut_stage_m: float = 3.0  # bridge closed when its reach stage >= this
    max_travel_min: int = 60
    sqm_per_person: float = 3.5  # Sphere minimum covered space
