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
    cors_origins: str = "http://localhost:5173,http://localhost:4173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
