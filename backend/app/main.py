import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import agents, aoi, drill, emulator, flow, forecast, health, history, improvements, layers, photos, runs, view3d
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

for r in (health.router, aoi.router, layers.router, runs.router, forecast.router, agents.router, history.router, photos.router, view3d.router, flow.router, emulator.router, drill.router, improvements.router):
    app.include_router(r)


@app.on_event("startup")
def _warm_flow_model() -> None:
    """Compile the flow model when an instance starts, not in the first Run on it (~20 s on Cloud Run). The numba cache
    can't ship in the image: Cloud Build's CPU may differ from Cloud Run's, and a mismatched cache is recompiled anyway."""
    import threading

    def warm() -> None:
        import time

        import numpy as np

        from app.engines import swe
        t = time.time()
        z = swe.condition(np.add.outer(np.arange(8.0), np.arange(8.0)))[0]  # _breach (60 m runs re-carve the ground)
        swe.simulate(z, 30.0, np.full(z.shape, 0.5), np.full(z.shape, 0.04), [20.0], 0.0, frame_s=3600)
        logging.getLogger(__name__).info("flow model compiled in %.1f s", time.time() - t)
    threading.Thread(target=warm, daemon=True).start()
