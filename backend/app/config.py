from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.local", extra="ignore")

    google_cloud_project: str = "project-0fd9c4ae-bf90-452f-a80"
    google_cloud_location: str = "global"  # VERIFY per chosen model (S0.10)
    google_genai_use_vertexai: bool = True
    gemini_model_fast: str = ""  # set after scripts/list_models.py
    gemini_model_pro: str = ""
    ee_project: str = "project-0fd9c4ae-bf90-452f-a80"
    gcs_bucket: str = "pravah-dss-data-project-0fd9c4ae-bf90-452f-a80"
    maps_server_key: str = ""  # from Secret Manager `maps-server-key`
    cors_origins: str = "http://localhost:5173,http://localhost:4173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
