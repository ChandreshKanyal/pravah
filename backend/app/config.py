from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.local", extra="ignore")

    google_cloud_project: str = "project-0fd9c4ae-bf90-452f-a80"
    google_cloud_location: str = "global"  # VERIFY per chosen model (S0.10)
    google_genai_use_vertexai: bool = True
    gemini_model_fast: str = "gemini-3.8-flash"  # decision D1: one model, different thinking levels
    gemini_model_pro: str = "gemini-3.8-flash"
    gemini_thinking_fast: str = "LOW"  # planner, analyst, photo classifier (MINIMAL is unsupported)
    gemini_thinking_pro: str = "HIGH"  # advisory brief
    ee_project: str = "project-0fd9c4ae-bf90-452f-a80"
    gcs_bucket: str = "pravah-dss-data-project-0fd9c4ae-bf90-452f-a80"
    maps_server_key: str = ""  # from Secret Manager `maps-server-key`
    stream_upa_km2: float = 5.0  # D3 default
    manning_n: float = 0.04
    # S3.2 runoff C by Dynamic World class: water, trees, grass, flooded_veg, crops, shrub_scrub, built, bare, snow_ice
    runoff_c: list[float] = [1.00, 0.25, 0.35, 0.60, 0.45, 0.40, 0.85, 0.60, 0.50]
    # S4.3 flood AHP matrix, order [hand, hist, dist_stream, upa, rain, slope, C]; editable by experts
    fsi_ahp_matrix: list[list[float]] = [
        [1, 1, 2, 2, 2, 2, 3], [1, 1, 1, 1, 1, 2, 2], [0.5, 1, 1, 1, 1, 2, 2], [0.5, 1, 1, 1, 1, 2, 2],
        [0.5, 1, 1, 1, 1, 1, 2], [0.5, 0.5, 0.5, 0.5, 1, 1, 1], [1 / 3, 0.5, 0.5, 0.5, 0.5, 1, 1]]
    # 2D flow model: 30 m cells x storm hours above this run on 60 m cells. 1.0 M (17 Oct, was 1.2 M): Rudraprayag 4 h
    # (1.15 M) took 142 s on Cloud Run at 30 m; at 60 m flooded area and people stayed within 4% (1.93 -> 2.00 km2,
    # 1,605 -> 1,608). Cities stay at 30 m: at 60 m Kalyan's people moved 2,525 -> 1,636 and Mumbai's 17,195 -> 21,172
    flow_max_cell_hours: int = 1_000_000
    apply_arf: bool = True  # TP-29 areal reduction of point rain in the rational method (spec: none)
    # S13 urban: rain up to this intensity is carried by storm drains (Mumbai's historical design standard is 25 mm/h;
    # BRIMSTOWAD upgrades target 50 mm/h). Only the excess ponds.
    urban_drain_capacity_mm_h: float = 25.0
    # Urban evacuation demand (still water): DEFRA/EA FD2321 hazard rating HR = d(v + 0.5) + DF with v = 0, DF = 0.5
    # reaches "danger for some" (0.75) at d = 0.5 m; fragile single-storey homes (F >= 0.75) at 0.3 m (water inside).
    # River mode keeps the spec's 0.05 m (fast flash floods in hill valleys).
    urban_evac_depth_m: float = 0.5
    urban_evac_depth_fragile_m: float = 0.3
    cors_origins: str = "http://localhost:5173,http://localhost:4173"
    # Sign-in and roles (app/auth.py). Local default: open, anonymous users act as default_role.
    auth_required: bool = False
    admin_emails: str = ""  # comma-separated; these accounts get the admin role
    default_role: str = "analyst"  # role for signed-in users without a users/{email} document (and anonymous when open)


@lru_cache
def get_settings() -> Settings:
    return Settings()
