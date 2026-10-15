from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.scenario import ScenarioParams


class ExposureSummary(BaseModel):
    total_pop: int = 0
    exposed_pop_by_hour: list[int] = []  # depth >= 0.05 m
    exposed_by_depth_band: dict[str, int] = {}  # "0.05-0.5","0.5-1.5",">1.5" at worst hour
    landslide_exposed_pop_by_hour: list[int] = []  # lsi_dyn class >= 4
    buildings_by_risk: dict[str, int] = {}
    clusters: list[dict] = []  # id "C1".., centroid, people, max_depth, dominant_class, risk


class TriageRow(BaseModel):
    structure_class: str
    risk_class: str
    buildings: int
    people: int


class BridgeStatus(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    lon: float
    lat: float
    first_closed_hour: int | None  # None = stays open in this scenario
    reason: str | None  # flood | bridge | landslide | blocked


class ShelterResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    kind: str
    lon: float
    lat: float
    capacity: int
    assigned: int
    spare: int
    status: str  # usable | flooded | landslide_risk | disabled | unreachable
    note: str = ""
    capacity_confidence: str = "low"


class RunResult(BaseModel):
    run_id: str
    aoi_id: str
    params: ScenarioParams
    created_at: datetime
    rain_series_mm_h: list[float]  # length H
    rain_label: str  # e.g. "Forecast day 3 (Thu), worst case x1.5"
    stage_by_reach_m: dict[str, list[float]]  # reach_id -> stage per hour (envelope)
    flooded_area_km2_by_hour: list[float]
    depth_png_urls: list[str]  # one URL per hour (coloured overlay)
    lsi_png_url: str = ""
    overlay_bounds: tuple[float, float, float, float]  # WGS84 bounds for overlays
    overlay_corners: list[list[float]] = []  # 4 corners for deck.gl BitmapLayer (UTM grid rotation)
    exposure: ExposureSummary = ExposureSummary()
    triage: list[TriageRow] = []
    roads_geojson_url: str = ""
    bridges: list[BridgeStatus] = []
    shelters: list[ShelterResult] = []
    routes_geojson_url: str = ""
    capacity_gap_people: int = 0
    assembly_points: list[dict] = []
    hotspots: list[dict] = []  # confluences / convergence points
    advisory_id: str | None = None
    warnings: list[str] = []  # data gaps, fallbacks used
    staging_points: list[dict] = []  # S7.8 ambulance/police/medical staging candidates
    routes: list[dict] = []  # top routes: people, eta_min, passable_until_h, to_shelter, use_now_gone_soon
    people_to_evacuate: int = 0
    timings_s: dict[str, float] = {}
    methods: dict = {}
    drains: list[dict] = []  # S13 urban: ranked drain/culvert inspection points (D1..)
    ponding_png_url: str = ""  # S13 urban: ponding likelihood at the last hour  # which formulas/thresholds this run used (shown on Methods and in the advisory)
