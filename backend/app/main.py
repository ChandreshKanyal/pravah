import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import agents, aoi, forecast, health, history, layers, photos, runs, view3d
from app.config import get_settings

logging.basicConfig(level=logging.INFO)
# httpx logs full request URLs at INFO, and Maps/Weather calls carry the API key as a query parameter
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="Pravah API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (health.router, aoi.router, layers.router, runs.router, forecast.router, agents.router, history.router, photos.router, view3d.router):
    app.include_router(r)
