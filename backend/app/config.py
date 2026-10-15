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
    cors_origins: str = "http://localhost:5173,http://localhost:4173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
