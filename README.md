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
.venv/bin/pytest -q                       # 65 tests (SPEC §7 T1-T15 + method, advisory, urban tests)

# frontend (Node 24); copy frontend/.env.example to frontend/.env.local and fill from docs/CONFIG.md
cd frontend && npm install && npx vite    # http://localhost:5173, proxies /api to :8080
```

Prepare an area: draw it on the Explore page, or `POST /api/aoi {"bbox": [W,S,E,N], "name": "..."}` and poll
`/api/aoi/{id}/status` (about 2-3 min for a new 10 km area; cached in GCS afterwards).

Demo areas (prepared, cached, with a showcase run and a Gemini advisory; re-run after engine changes):

| Area | Mode | aoi_id | Prepare + demo run |
|---|---|---|---|
| Rudraprayag 10 km (Alaknanda–Mandakini) | river | `56f044f26351` | `backend/.venv/bin/python scripts/preprocess_demo_aoi.py rudraprayag` |
| Mumbai Kurla–Mithi 3 km | urban | `d277268c1783` | `backend/.venv/bin/python scripts/preprocess_demo_aoi.py mumbai` |

Backtest (GFD overlap, sanity check): `backend/.venv/bin/python scripts/backtest.py <aoi_id> 100 6`.

## Deploy (Google Cloud only)

```bash
./scripts/deploy_backend.sh               # Cloud Build -> Cloud Run pravah-backend (asia-south1); CORS = Firebase domains
MIN_INSTANCES=1 ./scripts/deploy_backend.sh   # demo day only (S17.3); redeploy with 0 afterwards
cd frontend && npm run build && cd ..
~/.npm-global/bin/firebase deploy --only hosting --project project-0fd9c4ae-bf90-452f-a80
./scripts/smoke_test.sh                   # S17.4: health -> demo AOI -> run -> advisory (rules + Gemini) on the live URL
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
| POST / GET | `/api/runs/{id}/advisory` | S15 brief: POST starts a background Gemini job (`?rules_only=true` is instant), GET polls |
| POST | `/api/plan` | S14 scenario planner (ADK agent): text -> params diff; nothing runs until the user applies |
| POST | `/api/chat` | S14 analyst (ADK agent with tools); the UI now uses `/api/assistant` instead |
| GET | `/api/history/india`, `/api/history/aoi/{id}?web=` | S11 GFD tiles, NASA landslides, AOI events; `web=true` starts the grounded-search job |
| POST / GET | `/api/photos` | S12 field photo upload + Gemini vision classification; list per AOI |
| GET | `/api/aois`, `/api/geocode?q=` | recent areas; search box (Maps Geocoding, display only) |
| GET | `/api/aoi/{id}/3d/meta`, `dem.bin`, `base.jpg`, `imagery.jpg`, `buildings.json` | 3D view: the flow model's ground (FABDEM, conditioned), hillshade, Sentinel-2 true colour, building footprints |
| GET | `/api/runs/{id}/3d/risk.bin` | per-building risk codes for the 3D view |
| GET / POST | `/api/runs/{id}/flow` | 2D water-flow model for a run: status/summary; POST starts it (runs automatically after each scenario) |
| GET | `/api/runs/{id}/flow/frames.bin?model=flow\|hand` | water frames for the 3D animation (depth + velocity every 5 min, or the HAND map hourly), gzip |
| GET | `/api/runs/{id}/advisory/versions[/{n}]` | immutable brief versions with review state |
| POST | `/api/runs/{id}/advisory/review` | draft -> reviewed -> approved (name, designation, note); approved versions lock |
| POST | `/api/runs/{id}/advisory/translate?lang=hi` | Gemini translation; items whose numbers change stay in English |
| GET | `/api/runs/{id}/advisory/share.txt?lang=` | plain-text brief for WhatsApp/SMS/2G |
| GET | `/api/runs/{id}/audit` | audit trail for a run's brief |
| GET | `/api/aoi/{id}/runs?limit=&archived=` | saved runs (experiments) of an area: summary, title, notes, star, default |
| GET | `/api/projects` | Projects page: every area with run counts |
| PATCH | `/api/runs/{id}/meta` | name, notes, star, archive a run, or make it the area's default |
| GET/POST | `/api/aoi/{id}/emulator` | AI emulator of the 2D model: status and leave-one-out validation / start training |
| GET | `/api/aoi/{id}/emulator/predict[.png]?total_mm=&hours=&shape=&river_offset_m=` | instant what-if: stats or depth overlay |
| GET | `/api/aoi/{id}/triggers` | rain triggers per settlement (mm in 1/3/6 h, IMD category), from the 2D model |
| POST | `/api/runs/{id}/drill` · `/api/drills/{d}/answer` · `/api/drills/{d}/report` | Gemini tabletop drill: injects, scoring, after-action report |
| GET/POST | `/api/aoi/{id}/improvements` · `/api/aoi/{id}/improvements/img/{key}.png` | "Fix before the rain": places to maintain, with evidence (web, Sentinel-2 + Gemini review, model) |
| GET/POST | `/api/runs/{id}/alert` · `GET /api/runs/{id}/alert/cap.xml` | public alert draft (CAP 1.2, status Draft, EN + HI) for SACHET |
| PUT | `/api/aoi/{id}/official` | IMD colour code and CWC gauge levels entered by staff |
| POST | `/api/aoi/{id}/archive` | hide an area from the Explore list (reversible) |
| DELETE | `/api/runs/{id}` · `/api/aoi/{id}` | permanently delete a run (files, brief, 3D, alert, drills) or an area with all its runs |
| POST | `/api/assistant` · `/api/assistant/stream` | Ask Pravah: web-grounded answers, place search, analysis tools, proposed actions (SSE stream) |

## Code map

`backend/app/engines/` pure math (grid, hydrology, rainfall, flood, ahp, fsi, fr, landslide, buildings, population,
exposure, roads, shelters, routing, crowding, pluvial, drains, render, swe = 2D shallow-water flow model compiled with numba)
· `pipeline/flow.py` (background flow job per run) · `services/terrain.py` (FABDEM bare earth, breached for flow)
· `services/` I/O (Earth Engine, OSM, GCS, Firestore, Weather, Gemini, history) · `agents/` Gemini via ADK (planner, analyst + tools, historian) and the advisor ·
`pipeline/prepare_area.py` (static, per AOI) · `pipeline/run_pipeline.py` + `evac.py` (per scenario) · `pipeline/facts.py`
(advisory facts, validator, rules fallback, deadlines, supplies) · `services/places.py` (OSM place names) · `auth.py`
(Firebase sign-in, roles) · `api/` routes.
`frontend/src/` React + `@vis.gl/react-google-maps` + deck.gl + Terra Draw, Material Design 3 (Google Sans, Material
Symbols, `components/m3.tsx`); pages Explore, Workspace (Map), Advisory (Brief), Verify (Field check), Methods, 3D
(three.js water animation in `src/three/`: scene, water shaders, storm timeline).
Bridges as real OSM spans with deck heights: `engines/bridges.py` (backfill: `scripts/build_bridges.py`). AI emulator and
rain triggers: `engines/emulator.py`, `pipeline/emulator.py`, `src/components/AiPanel.tsx`. Drills: `agents/drill.py`,
`src/pages/Drill.tsx`. Public alerts: `agents/alerts.py`, `src/components/AlertDialog.tsx`. Projects: `src/pages/Projects.tsx`.
2D-model cross-check in Results: `src/components/ModelCheck.tsx`. Fix before the rain: `engines/improvements.py`,
`pipeline/improvements.py`, `src/components/ImprovementsPanel.tsx`. Assistant: `agents/assistant.py`,
`src/components/Assistant.tsx`. Deletion: `pipeline/cleanup.py`.
Sign-in: `src/auth.ts`; offline field photos: `src/offlineQueue.ts`.

## Data and licences

© OpenStreetMap contributors (ODbL) · Google Open Buildings (CC BY 4.0) · MERIT Hydro and Global Flood Database (CC BY-NC 4.0,
non-commercial) · FABDEM (CC BY-NC-SA 4.0, urban mode) · WorldPop · CHIRPS · NASA GPM IMERG · Dynamic World · Copernicus DEM
GLO-30 · JRC Global Surface Water · OpenLandMap · NASA Global Landslide Catalog · GRIP4 roads · Forecasts: Google Maps Platform
Weather API. The Methods page lists each licence. Google Maps content is used for display,
forecast and geocoding only, never as analysis input.
