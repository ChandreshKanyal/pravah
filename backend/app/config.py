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
    # S5.4 landslide AHP matrix, order [slope, rain, ndvi, drain, road, soil, curv, aspect]
    lsi_ahp_matrix: list[list[float]] = [
        [1, 1, 2, 2, 2, 2, 2, 3], [1, 1, 1, 2, 2, 2, 2, 3], [0.5, 1, 1, 1, 1, 1, 2, 2],
        [0.5, 0.5, 1, 1, 1, 1, 1, 2], [0.5, 0.5, 1, 1, 1, 1, 1, 2], [0.5, 0.5, 1, 1, 1, 1, 1, 2],
        [0.5, 0.5, 0.5, 1, 1, 1, 1, 1], [1 / 3, 1 / 3, 0.5, 0.5, 0.5, 0.5, 1, 1]]
    # S5.2 says drop records worse than 10 km; 5-10 km points cannot inform 90 m slope classes (FR came out
    # inverted for slope in Rudraprayag), so the default is 1 km. Set 10 to follow the spec literally.
    landslide_max_accuracy_km: float = 1.0
    # Landslide rain modulation and scope in routing (human decision 16 Oct: "soften + scope"; spec drift)
    lsi_g_slope: float = 0.25
    lsi_g_min: float = 0.75
    lsi_g_max: float = 1.25
    lsi_demand_class: int = 5  # buildings/grid people at or above this class need evacuation (spec: 4)
    lsi_shelter_max_class: int = 4  # shelters above this class are ruled out (spec: 3)
    lsi_close_share: float = 0.2  # road closes when this share of its length is class 5 (spec: any cell)
    # Rainfall I-D threshold for landslide modulation: "auto" = Dahal & Hasegawa (2008) in the Himalayan arc,
    # Caine (1980) elsewhere; or force "caine" / "dahal_hasegawa" (spec: Caine everywhere)
    lsi_threshold: str = "auto"
    # "class_shift": +-1 class by threshold exceedance (17 Oct); "graded_g": score x g (16 Oct); spec: score x clip(R)
    lsi_modulation: str = "class_shift"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
