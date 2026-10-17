from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RainSource(str, Enum):
    forecast = "forecast"
    worst = "worst"
    best = "best"
    historical_extreme = "historical_extreme"
    observed = "observed"  # actual rain of a past day (NASA GPM IMERG), `observed_date`
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
    upstream_inflow_m3s: float = 0.0  # river flow entering the area from outside (e.g. a CWC forecast), main stem total
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
    bridge_cut_stage_m: float = 3.0  # deprecated (one stage for every bridge); kept so old runs load
    bridge_margin_m: float = 0.0  # close a bridge when the river is within this many metres of its deck (0 = at the deck)
    max_travel_min: int = 60
    sqm_per_person: float = 3.5  # Sphere minimum covered space
    # IMD category or cloudburst (manual rain); the series and label are built by engines/rainfall.preset_series
    rain_preset: Literal["imd_heavy", "imd_very_heavy", "imd_extreme", "cloudburst"] | None = None
    preset_label: str | None = None  # e.g. "IMD very heavy rain (204 mm/day)": shown instead of the manual label
    # hourly mm/h used as-is (event replays, hour-by-hour edits); label from preset_label. Clamped to 0-300 mm/h (about
    # the world one-hour record, 305 mm): a runaway editor once sent 850 mm/h. Clamped, not rejected, so old runs still load
    rain_series_override: list[float] | None = None
    # storm-drain capacity under built-up land (mm/h); None = the area's confirmed value (drain lookup), else 25
    drain_capacity_mm_h: float | None = Field(default=None, ge=5, le=150)
    # the same three choices for every rain source (17 Oct): how the rain is spread over the hours ("source" keeps the
    # forecast's or the measured day's own pattern; None = the source's default, as before), how much stronger or weaker
    # than the source it is (x1 = the actual forecast / record / IMD category; the run label says when it is not), and for
    # record rain how rare a day (None = the wettest day on record; 2/10/25/100 = Gumbel estimate of that return period)
    rain_shape: Literal["source", "constant", "triangular_front"] | None = None
    rain_scale: float = Field(default=1.0, ge=0.1, le=5.0)
    return_period_y: Literal[2, 10, 25, 100] | None = None

    @field_validator("rain_series_override")
    @classmethod
    def _clamp_series(cls, v: list[float] | None) -> list[float] | None:
        return None if v is None else [min(300.0, max(0.0, float(x))) for x in v]
    override_start_local: str | None = None  # clock time of hour 1 for an override (an edited forecast keeps its clock)
    observed_date: str | None = None  # YYYY-MM-DD (local) for rain_source "observed"
    visitors: int = 0  # pilgrims/tourists present on top of residents, spread by the crowding index (S9)


RAIN_KEYS = {"rain_source", "rain_preset", "manual_intensity_mm_h", "forecast_day_index", "worst_multiplier", "duration_h",
             "hyetograph", "observed_date", "return_period_y"}


def apply_rain_change(p: dict, changed: set[str]) -> dict:
    """What the Scenario panel does when the rain changes, for every other writer (Gemini's plan, the assistant's tools):
    a new source starts as its actual data (strength x1, its own shape, the record day), an explicit hyetograph is the
    shape (rain_shape wins over hyetograph in the rain builder), and hand edits made for the old rain are dropped."""
    if not changed & RAIN_KEYS:
        return p
    if changed & {"rain_source", "rain_preset", "manual_intensity_mm_h", "observed_date"} and "rain_scale" not in changed:
        p["rain_scale"] = 1.0
    if "rain_source" in changed and "return_period_y" not in changed:
        p["return_period_y"] = None
    if "hyetograph" in changed:
        p["rain_shape"] = p["hyetograph"]
    elif changed & {"rain_source", "rain_preset"} and "rain_shape" not in changed:
        p["rain_shape"] = None
    p.update(rain_series_override=None, override_start_local=None, preset_label=None)
    return p
