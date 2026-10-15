# Pravah

Flood and landslide decision-support prototype for district authorities (Google AI Builder Cup 2026).
**Decision-support draft, not a prediction or an order.** Every result is an estimate for qualified officials to review.

- Spec: `docs/SPEC.md` · Cloud values: `docs/CONFIG.md` · Status and decisions: `docs/PROGRESS.md` · Agent rules: `AGENTS.md`

## Run locally

```bash
# backend (Python 3.12 via uv; needs gcloud ADC: gcloud auth application-default login)
uv venv --python 3.12 backend/.venv
uv pip install --python backend/.venv/bin/python -r backend/requirements.txt
cd backend && .venv/bin/uvicorn app.main:app --port 8080 --reload
.venv/bin/pytest -q                       # 47 tests (SPEC §7 T1-T15)

# frontend (Node 24); copy frontend/.env.example to frontend/.env.local and fill from docs/CONFIG.md
cd frontend && npm install && npx vite    # http://localhost:5173, proxies /api to :8080
```

Prepare an area: draw it on the Explore page, or `POST /api/aoi {"bbox": [W,S,E,N], "name": "..."}` and poll
`/api/aoi/{id}/status` (about 2-3 min for a new 10 km area; cached in GCS afterwards).

## Deploy (Google Cloud only)

```bash
./scripts/deploy_backend.sh               # Cloud Build -> Cloud Run pravah-backend (asia-south1)
cd frontend && npm run build && cd ..
~/.npm-global/bin/firebase deploy --only hosting --project project-0fd9c4ae-bf90-452f-a80
```

## API (backend)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | EE, Vertex (Gemini), Firestore checks |
| POST | `/api/aoi` | validate area, start background preparation |
| GET | `/api/aoi/{id}/status` | per-group preparation status, warnings, meta |
| GET | `/api/aoi/{id}/static-layers` | overlay PNG URLs, corners, hotspots, shelters, medical, crowding hotspots |
| GET | `/api/aoi/{id}/flood.png?stage=` | temporary uniform-stage flood overlay (S3 M1) |
| GET | `/api/aoi/{id}/verification-queue` | buildings to check in the field first (latest run) |
| GET | `/api/forecast?aoi_id=&duration_h=` | 240 h + 10 d forecast, past 90 d, screening strip |
| POST | `/api/runs` | ScenarioParams -> RunResult (flood, landslide, exposure, routing) |
| GET | `/api/runs/{id}` | stored RunResult |
| GET | `/api/layers/{aoi}/{name}.png`, `/api/runs/{id}/layers/{name}.png`, `/api/runs/{id}/files/{roads,routes}.geojson` | overlays |

## Code map

`backend/app/engines/` pure math (grid, hydrology, rainfall, flood, ahp, fsi, fr, landslide, buildings, population,
exposure, roads, shelters, routing, crowding, render) · `services/` I/O (Earth Engine, OSM, GCS, Firestore, Weather, Gemini) ·
`pipeline/prepare_area.py` (static, per AOI) · `pipeline/run_pipeline.py` + `evac.py` (per scenario) · `api/` routes.
`frontend/src/` React + `@vis.gl/react-google-maps` + deck.gl + Terra Draw; pages Explore and Workspace.

## Data and licences

© OpenStreetMap contributors (ODbL) · Google Open Buildings (CC BY 4.0) · MERIT Hydro and Global Flood Database (CC BY-NC 4.0,
non-commercial) · WorldPop · CHIRPS · NASA GPM IMERG · Dynamic World · Copernicus DEM GLO-30 · JRC Global Surface Water ·
NASA Global Landslide Catalog · Forecasts: Google Maps Platform Weather API. Google Maps content is used for display,
forecast and geocoding only, never as analysis input.
