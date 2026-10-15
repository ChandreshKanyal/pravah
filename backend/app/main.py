import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import aoi, health, layers, runs
from app.config import get_settings

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Pravah API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (health.router, aoi.router, layers.router, runs.router):
    app.include_router(r)
