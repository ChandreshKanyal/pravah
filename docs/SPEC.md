# Pravah: Disaster Decision-Support Platform

## Build Specification v1.0 (for coding agents)

| Field | Value |
|---|---|
| Hackathon | Google AI Builder Cup 2026 (Hack2skill, sponsored by Google Cloud) |
| Theme | Sustainability & Social Impact |
| Prototype deadline | **Sunday 18 Oct 2026**. Target submitting by 12:00 IST, not at the deadline. |
| Owner | Chandresh (planner and orchestrator). Code is written by AI coding agents. |
| Working name | **Pravah** (प्रवाह, "flow"). This is a placeholder; rename freely. |
| Primary demo area | A Himalayan valley town in Uttarakhand (suggested: Rudraprayag, at the Alaknanda–Mandakini confluence) |
| Secondary demo area | Mumbai urban water-logging (suggested: Mithi River / Kurla belt) |
| Doc status | v1.0, written 14 Oct 2026 |

---

## 0. How to use this document (read first, coding agent)

You are a coding agent. Build this project **one stage at a time** (Section 5). Each stage has:

- **Goal**: what exists when the stage is done.
- **Depends on**: stages that must already work.
- **Files**: where the code goes.
- **Steps**: numbered, bite-sized. Do them in order. One step is small enough to finish and test in one sitting.
- **Acceptance checks**: run these before moving on. Do not mark a stage done until they pass.
- **Pitfalls**: known traps.

### Rules for the agent

1. **Never invent an API, endpoint, field name or dataset ID.** Where this doc says **VERIFY**, open the linked official docs or the Earth Engine catalog and confirm before coding. If reality differs from this doc, follow reality and leave a `# NOTE(spec-drift): ...` comment.
2. **Only Google AI models and Google Cloud hosting.** See Section 2. Do not add OpenAI, Mapbox, AWS, Supabase, Vercel or similar.
3. **Never use Google Maps Platform content as analysis input.** Maps is for display only. Analysis data comes from Earth Engine and OpenStreetMap. See Section 2.2. This is a hard rule.
4. **Engines are pure Python functions.** They take numpy arrays and dataclasses and return numpy arrays and dataclasses. No HTTP, no Gemini, and no Earth Engine calls inside engine math. I/O lives in `services/`.
5. **Every engine function gets a unit test** with the worked numbers given in Section 7.
6. **Gemini never computes physics.** Gemini sets parameters, picks tools, interprets results and writes text. Numbers come from engines.
7. **Every user-facing output carries the decision-support disclaimer** (Section 2.4).
8. Where a step is marked **DECISION**, stop and ask the human.
9. Keep commits small: one step, one commit. The message starts with the step ID, e.g. `S3.4: rational method runoff`.

### Glossary

| Term | Meaning |
|---|---|
| AOI | Area of interest: the rectangle or polygon the user draws |
| DEM | Digital elevation model (grid of ground heights) |
| HAND | Height Above Nearest Drainage: a cell's height above the stream it drains into |
| D8 | Flow-direction method: each cell drains to its steepest of 8 neighbours |
| upa | Upstream drainage area (km²) of a cell, also called flow accumulation |
| Reach | A stream segment between confluences, used for the rating curve |
| SRC | Synthetic rating curve: discharge-to-stage relation built from HAND |
| Stage | Water surface height above the drainage (m) |
| FSI | Flood susceptibility index (0–1), static |
| LSI | Landslide susceptibility index (0–1), static, then rainfall-modulated |
| AHP | Analytic Hierarchy Process (pairwise-comparison weights) |
| FR | Frequency Ratio (weights learned from past landslide locations) |
| Run | One execution of the full pipeline for one scenario |
| Scenario | The adjustable inputs of a run (rain, hours, river offset, closures, etc.) |

---

## 1. The product in one page

**Problem.** When a cloudburst or flood threatens a hill town or a flood-prone city ward, district officials must decide quickly:

- who to move,
- by which road,
- to which shelter,
- which bridge to close,
- where to stage ambulances.

Today that knowledge is scattered across maps, forecasts, old reports and people's memory.

**What Pravah does.** An official draws an area on a map. Pravah then:

1. Shows **historical incidents** for the area: past floods and landslides as a heat map.
2. Pulls the **rain forecast** and builds a scenario: forecast, worst case, best case, a historical extreme, or manual.
3. **Simulates flooding hour by hour.** The chain is rainfall → runoff → river stage → HAND flood depth.
4. Scores **landslide susceptibility**, lit up by the scenario's rainfall.
5. Estimates **who is exposed**: people and buildings, triaged by flood depth and building fragility.
6. Plans **evacuation**: flood-aware and landslide-aware routes, capacity-aware shelter assignment, and a flag when shelter capacity runs short.
7. Writes an **advisory brief**: immediate, seasonal and structural actions, each with its evidence.
8. Lets the official **play what-if**: close a shelter, block a road, change the rain, re-run.

**Who it's for.** District disaster management authorities, municipal corporations, SDRF/NDRF planners and policymakers. A public read-only view comes later.

**What it is not.** It is not a prediction service and not an automated evacuation order. It is a **decision-support tool that produces a first draft for humans to review.** Every screen says so.

---

## 2. Non-negotiable rules

### 2.1 Challenge rules (AI Builder Cup 2026)

- The solution must run on **Google AI models** (Gemini or Gemma) or Google's agentic platforms (Agent Platform / ADK, AI Studio, Antigravity).
- It must be **deployed on Google Cloud via Cloud Run or Firebase**.
- **How we comply:**
  - All AI calls go to Gemini on Vertex AI, through the `google-genai` SDK and Google ADK.
  - The backend runs on Cloud Run and the frontend on Firebase Hosting.
  - All data, storage and compute services are Google Cloud: Earth Engine, Cloud Storage, Firestore and Cloud Run.
- **Allowed non-Google pieces.** The rules govern AI models and hosting, not libraries. These are allowed:
  - open-source libraries: OSMnx, NetworkX, NumPy, SciPy, React, deck.gl, Terra Draw;
  - open data: OpenStreetMap road and shelter data, which has no Google equivalent we may legally use for analysis (see 2.2).
  - Each non-Google item is listed with its reason in the spreadsheet.
- **IMD** (India Meteorological Department) is an **optional** forecast source. The default forecast is the Google Maps Platform Weather API.

### 2.2 Google Maps Platform Terms of Service: what we must NOT do

Maps Platform Terms §3.2.3 forbids several things we originally planned. Quoted from https://cloud.google.com/maps-platform/terms:

- §3.2.3(a): no exporting, extracting or scraping Google Maps Content for use outside the Services, including bulk download of "Street View images … elevation values".
- §3.2.3(b): no caching except where the Service Specific Terms allow it.
- §3.2.3(c): no creating content based on Google Maps Content. Examples it gives:
  - "(iii) build terrain models based on elevation values from the Elevation API"
  - "(iv) use latitude/longitude values from the Places API as an input for point-in-polygon analysis"
  - "(v) construct an index of tree locations within a city from Street View imagery"
  - "(vii) use Google Maps Content to improve machine learning and artificial intelligence models"

**What this changed in our locked design:**

| Original plan | Problem | Compliant replacement (USE THIS) |
|---|---|---|
| Terrain from Maps Elevation API | §3.2.3(c)(iii) | Terrain, slope and HAND from **Earth Engine** (Copernicus DEM, MERIT Hydro) |
| Gemini classifies buildings from Street View / Maps satellite | §3.2.3(a), (c)(v) | (1) Area-wide **proxy classification** from Google **Open Buildings** footprints and heights (Earth Engine). (2) **Gemini vision on field or drone photos uploaded by authorities** (their own images). |
| Gemini flags congestion from Street View | §3.2.3(a), (c)(v) | **Crowding index** from OpenStreetMap POIs, Open Buildings density and road width. The Maps **Traffic Layer** is shown to humans for display only. |
| Places API "busy area" points inside flood zones | §3.2.3(c)(iv) | OSM POIs for crowd attractors (markets, bus stands, schools, temples) |
| Road graph from Maps Roads/Routes | Bulk extraction | **OpenStreetMap via OSMnx** (open data, ODbL) |

**What Maps IS used for (allowed):**

- the base map,
- drawing our own overlays (flood, routes, risk) on top,
- the Traffic Layer as a visual,
- Street View panoramas **for a human to look at** (we never send them to Gemini or store them),
- Weather API forecasts,
- Geocoding for a search box,
- photorealistic 3D tiles in the optional 3D view.

### 2.3 Earth Engine and dataset licences

- Register the Cloud project for **noncommercial** Earth Engine use. The owner has decided the prototype is non-commercial research.
- Quota: Community tier, 150 EECU-hours/month. Contributor tier gives 1,000 EECU-hours/month and requires a billing account, which we have.
- **CC-BY-NC datasets:**
  - MERIT Hydro (HAND, flow direction, upstream area);
  - Global Flood Database.
  - If this ever goes commercial, these need a commercial licence or replacement. Note this in the pitch.
- **CC-BY datasets:** Open Buildings (v3 polygons and 2.5D Temporal). Attribute them in the UI footer.
- Show an **Attributions** section on the Methods page that lists every dataset and its licence.

### 2.4 Safety framing (exact strings)

Use this disclaimer on every results panel, the advisory brief and exports:

> **Decision-support draft, not a prediction or an order.** Pravah uses simplified, uncalibrated planning models (HAND flood mapping, rational-method runoff, susceptibility indices). Results are estimates for planning and must be reviewed by qualified officials before any action.

Other wording rules for the UI:

- Use "estimated", "susceptibility", "exposure" and "suggested". Never "will flood", "predicted collapse" or "safe".
- Shelters are "reachable in this scenario", not "safe".
- Building classes are "likely kaccha (proxy)" or "verified kaccha (field photo)".

---

## 3. Architecture

### 3.1 Component diagram

```
┌──────────────────────────── FRONTEND (Firebase Hosting) ─────────────────────────────┐
│ React + Vite + TS · @vis.gl/react-google-maps · deck.gl GoogleMapsOverlay · Terra Draw │
│ Pages: Explore · Workspace · Advisory · Field Verification · Methods · (3D)           │
└───────────────┬──────────────────────────────────────────────────────────────────────┘
                │ /api/** (Firebase Hosting rewrite → Cloud Run)
┌───────────────▼──────────────────── BACKEND (Cloud Run, FastAPI, Python 3.12) ───────┐
│ api/        REST endpoints                                                            │
│ agents/     Google ADK: scenario_planner · analyst · historian ; advisor (structured)  │
│ pipeline/   run_pipeline(params): fixed order S3→S5→S6→S8→S15                         │
│ engines/    pure math: hydrology · rainfall · flood · fsi · landslide · exposure ·    │
│             buildings · routing · crowding · pluvial · ahp · fr                       │
│ services/   I/O: earth_engine · osm · weather · gemini · storage · firestore          │
└──────┬─────────────┬───────────────┬───────────────┬──────────────┬─────────────────┘
       │             │               │               │              │
 Earth Engine   Vertex AI       Maps Platform     Cloud Storage   Firestore
 (DEM, MERIT,   (Gemini via     (Weather API,     (layer cache    (AOIs, scenarios,
 Open Bldgs,    google-genai    Geocoding, JS     .npz, photos,   runs, advisories,
 WorldPop, GFD, + ADK)          Maps display)     PNG overlays)   photo results)
 CHIRPS, IMERG,
 Dynamic World)                 OpenStreetMap via OSMnx (open data, roads/POIs/shelters)
```

### 3.2 What happens in one run

```
User draws AOI ──► POST /api/aoi ──► S1 prepare_area (cached per AOI)
                                         ├─ Earth Engine → grids (DEM, slope, HAND, dir, upa, landcover, pop, rain climatology, GFD)
                                         ├─ Earth Engine → buildings (footprints + heights)
                                         ├─ OSM → road graph, shelters, POIs, waterways
                                         └─ S2 hydrology prep (streams, reaches, catchments, SRC tables)
                                         └─ S4 FSI (static) · S5 LSI static · S6 building proxy classes · S9 crowding
User sets scenario (or asks in words → scenario_planner) ──► POST /api/runs
   run_pipeline(params):
     S10 rainfall series (forecast / worst / best / historical / manual)
     S3  hourly loop t=1..H: Q_t per reach → stage_t → depth_t grid (worst-case envelope)
     S5  LSI_dyn_t (rainfall-modulated)
     S6  exposure_t + triage
     S8  routing graph at decision hour, capacity-aware assignment, closure hours per route
     S15 facts JSON → Gemini advisory (validated) → fallback rules if invalid
   → store RunResult (Firestore + GCS PNGs) → frontend renders layers + brief
User tweaks (close shelter / block road / change rain) → new run (static layers reused, only dynamic parts recompute)
```

### 3.3 Stage dependency graph

```
S0 ─► S1 ─► S2 ─► S3 ─┬─► S6 ─► S8 ─► S14 ─► S15 ─► S16 ─► S17 ─► S18
            │         │    ▲      ▲
            ├─► S4 ───┤    │      │
            ├─► S5 ───┘────┘      │
            ├─► S7 ───────────────┘ (roads, shelters)
            └─► S9 ───────────────┘ (crowding)
S10 ─► S3 (rain input)      S11, S12, S13 plug into S16 + S15      S19 (3D) last, optional
```

### 3.4 Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Backend language | Python 3.12 | |
| Web framework | FastAPI + Uvicorn | |
| Earth Engine | `earthengine-api` | Use `ee.data.computePixels` (NUMPY_NDARRAY) for grids and `ee.data.computeFeatures` for vectors. **VERIFY** the current signatures. |
| Raster math | NumPy, SciPy (`ndimage`) | No GDAL dependency except via the `rasterio` wheel for rasterising vectors |
| Vector | Shapely 2, GeoPandas, `rasterio.features` | |
| Roads/POIs | OSMnx (2.x), NetworkX | **VERIFY** OSMnx 2.x function names (the module layout changed in 2.0) |
| AI | `google-genai` SDK (Vertex AI mode), `google-adk` | Gemini only |
| Storage | Cloud Storage (`google-cloud-storage`), Firestore (`google-cloud-firestore`) | |
| Frontend | React 18 + Vite + TypeScript | |
| Map | Google Maps JavaScript API via `@vis.gl/react-google-maps` | Google-maintained React wrapper |
| Overlays | deck.gl (`@deck.gl/google-maps` GoogleMapsOverlay) | Bitmap, GeoJSON and Heatmap layers |
| Drawing | **Terra Draw** + its Google Maps adapter | The Maps JS Drawing Library is **no longer available** (deprecated Aug 2025, removed May 2026) |
| Charts | Recharts or plain SVG | Follow the dataviz rules: accessible colours, labelled units |
| Hosting | Cloud Run (backend), Firebase Hosting (frontend, with a `/api/**` rewrite to Cloud Run) | |
| Region | `asia-south1` (Mumbai) for Cloud Run, Firestore and the GCS bucket | Gemini location: **VERIFY** which Vertex region or `global` endpoint serves the chosen model |

### 3.5 Repository layout

```
pravah/
├── README.md
├── docs/SPEC.md                      ← this file
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml / requirements.txt
│   ├── app/
│   │   ├── main.py                   FastAPI app, CORS, routers
│   │   ├── config.py                 env vars (pydantic-settings)
│   │   ├── models/                   pydantic schemas: aoi.py grid.py scenario.py run.py advisory.py photo.py
│   │   ├── api/                      aoi.py runs.py forecast.py history.py photos.py chat.py layers.py health.py
│   │   ├── services/                 earth_engine.py osm.py weather.py gemini.py storage.py firestore.py geocode.py
│   │   ├── engines/                  grid.py hydrology.py rainfall.py flood.py ahp.py fsi.py landslide.py fr.py
│   │   │                             buildings.py population.py exposure.py roads.py shelters.py routing.py
│   │   │                             crowding.py pluvial.py drains.py render.py
│   │   ├── pipeline/                 prepare_area.py run_pipeline.py facts.py
│   │   └── agents/                   tools.py scenario_planner.py analyst.py historian.py advisor.py prompts/
│   └── tests/                        test_*.py (one per engine) + fixtures/
├── frontend/
│   ├── index.html, vite.config.ts, package.json
│   └── src/
│       ├── main.tsx, App.tsx, router.tsx
│       ├── api/client.ts             typed fetch wrappers
│       ├── types/                    mirrors backend pydantic models
│       ├── pages/                    Explore.tsx Workspace.tsx Advisory.tsx Verify.tsx Methods.tsx View3D.tsx
│       ├── components/               MapCanvas.tsx DrawControl.tsx LayerPanel.tsx ScenarioPanel.tsx TimeSlider.tsx
│       │                             ResultCards.tsx TriageTable.tsx ShelterList.tsx RouteList.tsx AdvisoryList.tsx
│       │                             ForecastStrip.tsx ChatPanel.tsx Disclaimer.tsx Legend.tsx PhotoUploader.tsx
│       └── layers/                   deck.gl layer factories per data type
├── firebase.json, .firebaserc
└── scripts/                          preprocess_demo_aoi.py, deploy_backend.sh, deploy_frontend.sh
```

### 3.6 Environment variables (backend)

| Var | Example | Purpose |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | `pravah-dss` | Project ID |
| `GOOGLE_CLOUD_LOCATION` | `global` or `asia-south1` | Vertex AI location (**VERIFY** for the chosen model) |
| `GOOGLE_GENAI_USE_VERTEXAI` | `TRUE` | Route the google-genai SDK to Vertex AI, so the $300 credit applies |
| `GEMINI_MODEL_FAST` | from `client.models.list()` | Planner, analyst and photo classifier. Pick the current Flash model. Never hardcode a guessed name. |
| `GEMINI_MODEL_PRO` | from `client.models.list()` | Advisory brief. Pick the current Pro model. |
| `EE_PROJECT` | same as project | Earth Engine Cloud project |
| `GCS_BUCKET` | `pravah-dss-data` | Layer cache and photos |
| `MAPS_SERVER_KEY` | secret | Weather API and Geocoding (server-side key, API-restricted) |
| `CORS_ORIGINS` | Firebase URL | |

Frontend (`.env`): `VITE_MAPS_BROWSER_KEY` (HTTP-referrer-restricted), `VITE_MAP_ID` (a Map ID with vector rendering), `VITE_API_BASE=/api`.

---

## 4. Shared data contracts

Define these in `backend/app/models/` (pydantic) and mirror them in `frontend/src/types/`. **Every stage reads and writes these shapes. Do not invent ad-hoc shapes.**

### 4.1 AOI

```python
class AOI(BaseModel):
    aoi_id: str                 # sha1 of rounded bbox string, first 12 chars
    name: str                   # user label or reverse-geocoded place
    bbox: tuple[float,float,float,float]   # (west, south, east, north) WGS84
    polygon_geojson: dict | None            # optional; bbox is the analysis extent
    mode: Literal["river", "urban"] = "river"   # river = HAND flood; urban = pluvial screening (S13)
    created_at: datetime
```

Limits:

- Max AOI size is **15 km × 15 km**. The UI must block larger selections with a message.
- Hydrology uses the AOI **buffered by 3 km**. Display crops back to the AOI.

### 4.2 Analysis grid

All rasters for one AOI share **one grid**:

- **CRS:** the UTM zone of the AOI centroid. Uttarakhand and Mumbai are both in UTM 43N/44N: lon 72–78°E is zone 43 (EPSG:32643) and lon 78–84°E is zone 44 (EPSG:32644). Compute it as `zone = int((lon + 180) / 6) + 1`, giving EPSG `32600 + zone`.
- **Cell size:** 30 m.
- **Extent:** the buffered AOI bbox, transformed to UTM, snapped outward to multiples of 30 m.

```python
@dataclass(frozen=True)
class GridSpec:
    crs: str          # "EPSG:32644"
    x0: float         # upper-left x (m)
    y0: float         # upper-left y (m)
    cell: float       # 30.0
    width: int        # columns
    height: int       # rows
    # affine: x = x0 + col*cell ; y = y0 - row*cell
```

**Storage.** Save one `.npz` per AOI layer group at `gs://$GCS_BUCKET/aoi/{aoi_id}/{group}.npz`, with a `grid.json` beside it. Use float32 for continuous values, int16/uint8 for classes and `NaN` for nodata.

Layer keys (exact names):

| Key | Source | Unit |
|---|---|---|
| `dem` | Copernicus DEM | m |
| `slope_deg` | from `dem` | degrees |
| `aspect_deg` | from `dem` | degrees (0 = N) |
| `curv` | from `dem` | 1/100 m (general curvature) |
| `hand` | MERIT `hnd` | m |
| `d8` | MERIT `dir` | code 1,2,4,…,128 |
| `upa` | MERIT `upa` | km² |
| `elv_hydro` | MERIT `elv` | m |
| `lc_class` | Dynamic World mode `label` | 0–8 |
| `ndvi` | Sentinel-2 median | −1..1 |
| `soil_clay` | OpenLandMap clay fraction | % |
| `rain_clim` | CHIRPS mean annual max 1-day | mm |
| `gfd_count` | Global Flood DB | events |
| `gsw_occ` | JRC Global Surface Water occurrence | % |
| `pop100` | WorldPop at 100 m, resampled by sum (see S6) | people/cell |
| `dist_road_m` | from OSM roads | m |
| `dist_stream_m` | from stream mask | m |
| `stream` | `upa >= STREAM_UPA_KM2` | bool |
| `reach_id` | S2 | int32 (−1 = none) |
| `drain_cell` | S2 | int32 flat index |
| `fsi` | S4 | 0–1 |
| `lsi_static` | S5 | 0–1 |

### 4.3 ScenarioParams

```python
class RainSource(str, Enum):
    forecast = "forecast"; worst = "worst"; best = "best"
    historical_extreme = "historical_extreme"; manual = "manual"

class ScenarioParams(BaseModel):
    aoi_id: str
    rain_source: RainSource = RainSource.forecast
    forecast_day_index: int | None = None     # 0..9; None = auto-pick worst day
    manual_intensity_mm_h: float = 50.0       # for manual
    duration_h: int = 4                       # 1..24 hours simulated
    hyetograph: Literal["constant","triangular_front"] = "constant"
    worst_multiplier: float = 1.5             # worst = forecast × this
    best_multiplier: float = 0.5
    river_offset_m: float = 0.0               # added to every reach stage (pre-existing high water)
    manning_n: float = 0.04
    pop_multiplier: float = 1.0
    pop_total_override: int | None = None
    disabled_shelter_ids: list[str] = []
    extra_shelters: list[dict] = []           # {id,name,lat,lng,capacity}
    blocked_polygons: list[dict] = []         # GeoJSON polygons drawn by user
    travel_mode: Literal["walk","drive"] = "walk"
    evac_start_hour: int = 1                  # decision hour for routing
    vehicle_depth_limit_m: float = 0.3
    walk_depth_limit_m: float = 0.5
    bridge_cut_stage_m: float = 3.0           # bridge closed when its reach stage ≥ this
    max_travel_min: int = 60
    sqm_per_person: float = 3.5               # Sphere minimum covered space
```

Every field has a default, so `{"aoi_id": "..."}` alone is a valid scenario.

### 4.4 RunResult (stored at Firestore `runs/{run_id}`; large arrays in GCS)

```python
class RunResult(BaseModel):
    run_id: str; aoi_id: str; params: ScenarioParams; created_at: datetime
    rain_series_mm_h: list[float]                 # length H
    rain_label: str                               # e.g. "Forecast day 3 (Thu), worst case ×1.5"
    stage_by_reach_m: dict[str, list[float]]      # reach_id → stage per hour (envelope)
    flooded_area_km2_by_hour: list[float]
    depth_png_urls: list[str]                     # one signed URL per hour (colored overlay)
    lsi_png_url: str; overlay_bounds: tuple[float,float,float,float]  # WGS84 bounds for overlays
    exposure: ExposureSummary                     # see S6
    triage: list[TriageRow]
    roads_geojson_url: str                        # edges with status per hour
    bridges: list[BridgeStatus]
    shelters: list[ShelterResult]                 # capacity, assigned, spare, status
    routes_geojson_url: str
    capacity_gap_people: int
    assembly_points: list[dict]
    hotspots: list[dict]                          # confluences / convergence points
    advisory_id: str | None
    warnings: list[str]                           # data gaps, fallbacks used
```

### 4.5 Advisory (structured output from Gemini; validated)

```python
class Recommendation(BaseModel):
    id: str                                   # "R1"..
    horizon: Literal["immediate","seasonal","structural"]
    priority: Literal["P1","P2","P3"]
    action: str                               # imperative, ≤ 25 words
    location_label: str
    evidence_ids: list[str]                   # MUST reference ids present in the facts JSON
    why: str                                  # ≤ 40 words, cites numbers from facts
    confidence: Literal["low","medium","high"]

class Advisory(BaseModel):
    advisory_id: str; run_id: str
    headline: str                             # ≤ 30 words
    key_numbers: list[dict]                   # {label, value, unit, evidence_id}
    recommendations: list[Recommendation]
    limitations: list[str]
    disclaimer: str                           # exact string from §2.4
    generated_by: Literal["gemini","rules_fallback"]
```

### 4.6 Firestore collections

- `aois/{aoi_id}`: AOI, layer status per group, `prepared_at`.
- `runs/{run_id}`: RunResult (without large arrays).
- `advisories/{advisory_id}`
- `photos/{photo_id}`: upload metadata and Gemini classification.
- `history_cache/{aoi_id}`: grounded incident list and its sources.

### 4.7 REST API (backend)

| Method | Path | Body / Query | Returns |
|---|---|---|---|
| GET | `/api/health` | | `{ok, ee, vertex, firestore}` |
| POST | `/api/aoi` | `{bbox, name?, mode?}` | `AOI` + preparation job status |
| GET | `/api/aoi/{id}/status` | | layer groups ready/pending |
| GET | `/api/aoi/{id}/static-layers` | | URLs of FSI, LSI static, HAND, buildings, roads, shelters, crowding overlays |
| GET | `/api/forecast?aoi_id=` | | hourly (240 h) + daily (10 d) rain, alerts, worst day |
| POST | `/api/runs` | `ScenarioParams` | `RunResult` (sync; target < 20 s for a 10 km AOI) |
| GET | `/api/runs/{id}` | | `RunResult` |
| POST | `/api/runs/{id}/advisory` | | `Advisory` |
| POST | `/api/plan` | `{aoi_id, text, current_params}` | `ScenarioParams` (from natural language) |
| POST | `/api/chat` | `{session_id, aoi_id, run_id?, message}` | `{reply, new_run_id?}` |
| GET | `/api/history/india` | | EE tile URLs (GFD heat, GSW) + landslide points |
| GET | `/api/history/aoi/{id}` | | incidents (datasets + grounded web) with sources |
| POST | `/api/photos` | multipart image + `{aoi_id, kind: building|drain, lat?, lng?}` | classification result |
| GET | `/api/aoi/{id}/verification-queue` | | buildings ranked for field inspection |

---

## 5. Build stages

Priority tags:

- **P0**: the demo fails without it.
- **P1**: in scope, build after P0 works.
- **P2**: in scope, build last.
- **OPT**: only if time allows (3D).

---

### S0: Project and cloud setup (P0)

**Goal:** an empty FastAPI app and an empty React app are deployed and talking to each other, and every Google service answers a health check.

**Depends on:** nothing.

**Steps:**

- **S0.1** In the Cloud Console, use the project that has the **$300 free-trial billing account** linked. If you create a new project, link it to that same trial billing account so the credit applies, including to Maps APIs. Note the project ID.
- **S0.2** Enable the APIs with `gcloud services enable`:
  - `run.googleapis.com`, `cloudbuild.googleapis.com`, `artifactregistry.googleapis.com`
  - `firestore.googleapis.com`, `storage.googleapis.com`, `aiplatform.googleapis.com`
  - `earthengine.googleapis.com`, `secretmanager.googleapis.com`
  - `maps-backend.googleapis.com` (Maps JavaScript API), `weather.googleapis.com`, `geocoding-backend.googleapis.com`, `tile.googleapis.com` (Map Tiles, for 3D)
  - **VERIFY** each service name in the API Library if `gcloud` rejects it.
- **S0.3** Register the project for **noncommercial Earth Engine** use in the Earth Engine registration flow (Code Editor → Register a Noncommercial project). Choose the Contributor tier if offered.
- **S0.4** Create service account `pravah-backend@…` and grant it:
  - Vertex AI User
  - Earth Engine Resource Writer (`roles/earthengine.writer`; **VERIFY** the role name in the EE docs)
  - Service Usage Consumer
  - Cloud Datastore User
  - Storage Object Admin, on the bucket only
  - Secret Manager Secret Accessor
- **S0.5** Create the GCS bucket `pravah-dss-data` in `asia-south1` (uniform access, not public). Create the Firestore database in Native mode in `asia-south1`.
- **S0.6** Create two API keys:
  - **browser key:** restrict to the Maps JavaScript API and Map Tiles API, with HTTP referrers = your Firebase domains and `localhost`;
  - **server key:** restrict to the Weather API and Geocoding API. Store it in Secret Manager as `maps-server-key`.
- **S0.7** In Maps Platform → Map Management, create a **Map ID** (JavaScript, vector). Put it in `VITE_MAP_ID`.
- **S0.8** Under Billing → Budgets, create a budget of $100 with alerts at 25%, 50%, 75% and 100%.
- **S0.9** Scaffold the repo exactly as in §3.5. Backend dependencies:
  `fastapi uvicorn[standard] pydantic-settings earthengine-api google-genai google-adk google-cloud-storage google-cloud-firestore google-cloud-secret-manager numpy scipy pyproj shapely geopandas rasterio osmnx networkx pillow httpx`
  Pin versions after the first successful install.
- **S0.10** Write `scripts/list_models.py`. It creates a `genai.Client(vertexai=True, project=..., location=...)` and prints the model names that contain "gemini". **DECISION:** the human picks `GEMINI_MODEL_FAST` and `GEMINI_MODEL_PRO` from that list.
- **S0.11** Implement `GET /api/health`. It returns `ok` only when all three checks pass:
  - `ee.Initialize(project=EE_PROJECT)` and `ee.Number(1).getInfo()` succeed;
  - a one-line Gemini call returns text;
  - a Firestore write and read of `health/ping` succeeds.
- **S0.12** Write a Dockerfile (python:3.12-slim). Deploy to Cloud Run with:
  - `--region asia-south1 --service-account pravah-backend@… --memory 4Gi --cpu 2 --timeout 900 --no-cpu-throttling`
  - the env vars from §3.6.
- **S0.13** Run `firebase init hosting` with the frontend build dir `frontend/dist`. In `firebase.json`, add the rewrite `{"source": "/api/**", "run": {"serviceId": "pravah-backend", "region": "asia-south1"}}`. Deploy a "Hello Pravah" page that calls `/api/health` and shows the result.

**Acceptance:**

- The deployed Firebase URL shows `ee ✓ vertex ✓ firestore ✓`.
- `scripts/list_models.py` prints at least one Gemini model.

**Pitfalls:**

- Earth Engine on Cloud Run uses the service account's default credentials. Call `ee.Initialize(project=...)` once at startup, not per request.
- Without `--no-cpu-throttling`, background tasks freeze after the HTTP response.

---

### S1: AOI and base-layer ingestion (P0)

**Goal:** for any drawn rectangle, every layer key in §4.2 is fetched, aligned to one 30 m grid and cached in GCS. Buildings, roads, POIs and waterways are cached as vectors.

**Depends on:** S0.

**Files:** `models/aoi.py`, `models/grid.py`, `engines/grid.py`, `services/earth_engine.py`, `services/osm.py`, `services/storage.py`, `pipeline/prepare_area.py`, `api/aoi.py`.

**Steps:**

- **S1.1** In `models/aoi.py`, build `AOI`:
  - `aoi_id = sha1(f"{w:.4f},{s:.4f},{e:.4f},{n:.4f}")[:12]`;
  - validate the max size: river mode ≤ 15 km × 15 km, urban mode ≤ 4 km × 4 km. Raise `422` with a clear message.
- **S1.2** In `engines/grid.py`:
  - `utm_epsg(lon, lat)`;
  - `make_grid(bbox, buffer_m=3000, cell=30) -> GridSpec`: transform the bbox corners to UTM with `pyproj.Transformer(always_xy=True)`, buffer, then snap outward to multiples of 90 m so the grid is divisible by 3.
  - Helpers: `cell_centers_xy(grid)`, `xy_to_rowcol(grid, x, y)`, `rowcol_to_lonlat(grid, r, c)`, `corner_lonlats(grid)` (4 corners, for deck.gl).
  - Unit-test a round trip: lon/lat → row/col → lon/lat lands within 30 m.
- **S1.3** In `services/earth_engine.py`, write `fetch_grid(image: ee.Image, grid: GridSpec, bands: list[str]) -> dict[str, np.ndarray]` using `ee.data.computePixels`:
  - `{"expression": image.select(bands), "fileFormat": "NUMPY_NDARRAY", "grid": {"dimensions": {"width": W, "height": H}, "affineTransform": {"scaleX": cell, "shearX": 0, "translateX": x0, "shearY": 0, "scaleY": -cell, "translateY": y0}, "crsCode": crs}}`;
  - the result is a structured array; return each band as `float32` (or its native integer type);
  - **VERIFY** the request shape in the current `earthengine-api` docs. Tile requests larger than about 48 MB: split into 2×2 blocks.
- **S1.4** Write `resample(image, kind)`. `kind="bilinear"` calls `.resample('bilinear')`. `kind="nearest"` leaves the image alone (nearest is the default). **Never** use bilinear on class or code layers (`lc_class`, `d8`, `upa`, `gfd_count`).
- **S1.5** Fetch each layer with exactly these expressions (**VERIFY** each ID in the EE catalog before running):

  | Key | Expression | Resampling |
  |---|---|---|
  | `dem` | `ee.ImageCollection(DEM_ID).filterBounds(r).select('DEM').mosaic().setDefaultProjection(ee.ImageCollection(DEM_ID).first().projection())` with `DEM_ID` = the **current** Copernicus GLO-30 collection (`COPERNICUS/DEM/GLO30` is marked deprecated, superseded by `COPERNICUS/DEM/GLO30_2024_1`; **VERIFY**) | bilinear |
  | `hand`, `elv_hydro` | `ee.Image('MERIT/Hydro/v1_0_1').select(['hnd','elv'])` | bilinear |
  | `upa` (30 m copy, display/stream mask only) | `ee.Image('MERIT/Hydro/v1_0_1').select('upa')` | nearest |
  | `lc_class` | `ee.ImageCollection('GOOGLE/DYNAMICWORLD/V1').filterBounds(r).filterDate(today-365d, today).select('label').mode()` | nearest |
  | `ndvi` | `ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(r).filterDate(<last Oct 1>, <last Mar 31>).filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)).median().normalizedDifference(['B8','B4'])` | bilinear |
  | `soil_clay` | OpenLandMap clay fraction, surface band (e.g. `OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02`, band `b0`; **VERIFY**) | bilinear |
  | `rain_clim` | CHIRPS `UCSB-CHG/CHIRPS/DAILY` `precipitation` (mm/d). For each year 2001–2024: `.filterDate(year).max()`. Then take the mean of the 24 annual-max images. | bilinear |
  | `gfd_count` | `ee.ImageCollection('GLOBAL_FLOOD_DB/MODIS_EVENTS/V1').select('flooded').sum()` | nearest |
  | `gsw_occ` | JRC Global Surface Water `occurrence` (e.g. `JRC/GSW1_4/GlobalSurfaceWater`; **VERIFY** the latest version) | bilinear |
  | `pop_density` | `wp = ee.ImageCollection('WorldPop/GP/100m/pop').filter(ee.Filter.eq('country','IND')).filter(ee.Filter.eq('year', 2020)).mosaic()` (**VERIFY** the latest year). Then `wp.divide(ee.Image.pixelArea().reproject(wp_native_projection))` gives people/m². | nearest |

- **S1.6** Derive `pop30 = pop_density × 900`. Rescale so `pop30.sum()` equals the AOI total from `wp.reduceRegion(ee.Reducer.sum(), region, scale=native)`. Log both totals.
- **S1.7** Compute terrain derivatives **in NumPy from `dem`**, not with `ee.Terrain`, to avoid projection pitfalls. Rows increase southward.
  - `gx = np.gradient(dem, axis=1) / cell` (east)
  - `gy = -np.gradient(dem, axis=0) / cell` (north)
  - `slope_deg = degrees(arctan(hypot(gx, gy)))`
  - `aspect_deg = (degrees(arctan2(-gx, -gy)) + 360) % 360`. Set it to `-1` where `slope_deg < 1`.
  - `curv = -100 * (d2z/dx2 + d2z/dy2)`, using `np.gradient` twice. Negative means concave.
- **S1.8** Buildings, in `services/earth_engine.py::fetch_buildings(aoi)`:
  1. `fc = ee.FeatureCollection('GOOGLE/Research/open-buildings/v3/polygons').filterBounds(r).filter(ee.Filter.gte('confidence', 0.70))`.
  2. Heights: `img23 = ee.ImageCollection('GOOGLE/Research/open-buildings-temporal/v1').filterBounds(r).filterDate('2023-01-01','2024-01-01').mosaic()`, then `img23.select(['building_height','building_presence']).reduceRegions(fc, ee.Reducer.mean(), scale=4)`.
  3. Repeat with the `2016-…` image, keeping only `building_presence` as `presence_2016`.
  4. Export with `ee.data.computeFeatures(... fileFormat='GEOPANDAS_GEODATAFRAME')` (**VERIFY**; otherwise page through with `toList`).
  5. Project to the grid CRS and save as `buildings.parquet`. Columns: `bid, geometry, area_m2, confidence, height_m, presence_2023, presence_2016`.
  6. If the count is 0, add the warning "No Open Buildings coverage here" to `warnings`.
- **S1.9** OSM, in `services/osm.py` (OSMnx 2.x; **VERIFY** function names):
  - graphs `G_walk` and `G_drive` from the buffered bbox (`network_type="walk"` / `"drive"`, `simplify=True`), saved as GraphML in GCS;
  - POIs via `features_from_bbox` with tags `{"amenity": True, "shop": True, "tourism": ["hotel","guest_house","hostel"], "public_transport": ["station"], "railway": ["station"], "building": ["school","hospital","temple","public"]}`, saved as `pois.parquet`;
  - waterways via `features_from_bbox` with `{"waterway": ["river","stream","drain","canal","ditch"], "tunnel": ["culvert"]}`, saved as `waterways.parquet`;
  - wrap every call in a 3-attempt retry with backoff, because the Overpass API rate-limits. On failure, add a warning and continue.
- **S1.10** Distance rasters:
  - `dist_road_m`: rasterise `G_drive` edge geometries with `rasterio.features.rasterize`, then `scipy.ndimage.distance_transform_edt(~road_mask) * cell`;
  - `stream = upa >= STREAM_UPA_KM2` (default 5, from config);
  - `dist_stream_m` the same way from `stream`.
- **S1.11** `services/storage.py`: `save_layers(aoi_id, group, dict_of_arrays, grid)` writes `.npz` + `grid.json`. `load_layers(aoi_id, group)` reverses it. Use groups `terrain`, `hydro30`, `landcover`, `hazard_hist`, `population`, `derived`.
- **S1.12** `pipeline/prepare_area.py::prepare_area(aoi)` runs S1.5–S1.11, then S2, S4, S5 (static), S6.1–S6.3, S7.1–S7.6 and S9. Write status per group to `aois/{aoi_id}`. It is **idempotent**: skip groups already in GCS.
- **S1.13** `POST /api/aoi` validates, writes the AOI doc and starts `prepare_area` as a FastAPI `BackgroundTask`. `GET /api/aoi/{id}/status` returns the group statuses.
- **S1.14** `engines/render.py`:
  - `to_png(array, colormap, vmin, vmax, nodata_transparent=True) -> bytes` (Pillow RGBA);
  - `overlay_payload(grid) -> {"corners": corner_lonlats(grid)}`. deck.gl `BitmapLayer` accepts **four corner coordinates**, which corrects the UTM grid rotation (about 1° near Rudraprayag; ignoring it shifts edges by about 130 m).
  - Upload PNGs to GCS and return V4 signed URLs valid for 24 h.

**Acceptance:**

- For a 10 km Rudraprayag box, `prepare_area` finishes in under 3 minutes.
- Every key in §4.2 exists with the same shape.
- The DEM range is plausible (roughly 600–2,500 m there).
- `pop30.sum()` is within 1% of the EE total.
- The HAND overlay PNG lines up with the rivers on the Google satellite base map.

**Pitfalls:**

- A mosaic of an ImageCollection has no default projection. Set one before any spatial operation.
- WorldPop's latest year may differ, so **VERIFY** it.
- Open Buildings coverage of India is not stated per country on the catalog page. Check the count and warn if it is zero.

---

### S2: Hydrology preparation (P0)

**Goal:** stream network, reaches, local contributing area, catchment-per-cell, convergence hotspots and a synthetic rating curve (SRC) table for every reach.

**Depends on:** S1.

**Why a separate grid:** MERIT Hydro flow directions (`dir`) are defined on MERIT's own geographic 3-arcsecond grid. Resampling D8 codes to UTM breaks connectivity, so **all D8 work happens on the native MERIT grid**. Results are mapped to the 30 m grid afterwards.

**Files:** `engines/hydrology.py`, `services/earth_engine.py`.

**Steps:**

- **S2.1** Define `HydroGrid`:
  - CRS `EPSG:4326`, cell = 1/1200 degree (3″);
  - origin snapped **outward** to multiples of 1/1200° around the buffered AOI;
  - cell sizes in metres: `dy = 92.66`, `dx = 92.66 * cos(radians(lat_center))`, with `cell_area = dx * dy`;
  - fetch `hnd, dir, upa, elv` from `MERIT/Hydro/v1_0_1` with `computePixels` on this grid using `crsCode: "EPSG:4326"`, **no resampling**.
- **S2.2** `d8_offsets = {1:(0,1), 2:(1,1), 4:(1,0), 8:(1,-1), 16:(0,-1), 32:(-1,-1), 64:(-1,0), 128:(-1,1)}` (drow, dcol). Codes 0 and −1, and any target outside the grid, mean "outlet". Build `downstream: int32[N]` (flat index or −1).
- **S2.3** Local accumulation (`A_local_km2`):
  1. Compute in-degree from `downstream`.
  2. Run Kahn's topological order: start from cells with in-degree 0, push each cell's accumulated area to its downstream cell, and decrement in-degree.
  3. `A_local = (cells upstream inside grid + 1) × cell_area / 1e6`.
  - This is the area **inside the grid** that drains to each cell. The scenario storm falls on it. Water from outside the grid is handled by `river_offset_m` / `upstream_inflow`.
- **S2.4** `stream = upa >= STREAM_UPA_KM2` (MERIT `upa`, full upstream area, so tributaries are recognised even if their basin leaves the grid).
- **S2.5** `drain_cell` for every cell: the first stream cell reached by following `downstream`. Start with `t = where(stream, idx, downstream)`. Loop: wherever `t != -1` and `not stream[t]`, set `t = downstream[t]`. Stop when nothing changes (cap at 20,000 iterations). Cells that reach −1 get −1.
- **S2.6** Reaches:
  1. For each stream cell, `n_up = number of stream cells whose downstream is it`.
  2. A **reach head** is a stream cell with `n_up != 1`, or whose downstream cell is a confluence.
  3. From each head, walk downstream assigning `reach_id` until you hit the next head, an outlet, or a length ≥ 2,000 m. Splitting at 2 km starts a new reach.
  - Step length: `dx` for E/W, `dy` for N/S, `hypot(dx,dy)` for diagonals.
  - Per reach, store:
    - `L_m` (sum of steps);
    - `e_up`, `e_down` (MERIT `elv` at the first and last cell);
    - `S = clamp((e_up - e_down)/L_m, 0.001, 0.5)`;
    - `A_up_km2` (MERIT `upa` at the last cell);
    - `A_loc_km2` (`A_local` at the last cell);
    - `cells` (flat indices);
    - `centroid_lonlat`.
- **S2.7** `catch_reach[cell] = reach_id[drain_cell[cell]]` (−1 if none).
- **S2.8** Local slope for bed area: `S_ij` = magnitude of the gradient of MERIT `elv`, using the cell `dx`, `dy`.
- **S2.9** SRC per reach (the method of Zheng et al. 2018, as in TauDEM CatchHydroGeo). For each stage `h` in `0.0, 0.25, …, 30.0`, over cells with `catch_reach == r` and `hnd < h`:
  - `V = Σ (h − hnd_ij) · cell_area`
  - `A_b = Σ cell_area · sqrt(1 + S_ij²)`
  - `A = V / L_m`, `P = A_b / L_m`, `R = A / P` (0 if P = 0)
  - `Q = A · R^(2/3) · S^(1/2) / n` (n = `manning_n`, default 0.04)
  - Make `Q` monotone (`np.maximum.accumulate`) and store `{h: [...], Q: [...]}` per reach.
  - Recompute only when `manning_n` changes. Cache keyed by n.
- **S2.10** `src_stage(reach, Q)` = `np.interp(Q, Q_table, h_table)`, clipped to `[0, 30]`.
- **S2.11** Convergence hotspots:
  - stream cells with `n_up >= 2` (confluences), plus stream cells where `upa` rises by more than 50% from the largest upstream stream neighbour;
  - output `[{id: "H1", lon, lat, upa_km2, type: "confluence"|"surge"}]`, keeping the top 15 by `upa`.
- **S2.12** Map to the 30 m grid: for each G30 cell centre, convert to lon/lat (pyproj), then hydro row/col (`floor`). Store `reach_id_30 = catch_reach[hydro_idx]` (int32, −1 if outside). Save with the `hydro30` group.

**Acceptance:**

- Rudraprayag box: more than 10 reaches, and the largest `A_up_km2` is above 1,000 km² (the Alaknanda).
- The stream overlay follows the visible rivers.
- Every reach's `Q` table is non-decreasing, with `Q(0) = 0`.
- The unit test from §7 (toy SRC) passes.

**Pitfalls:**

- MERIT `hnd` is relative to MERIT's own drainage definition, which can differ slightly from our `STREAM_UPA_KM2`. Accept this and note it in Methods.
- Don't loop in pure Python over more than 1 M cells. A 21 km buffered box at 3″ is about 230×250 cells, which is fine.

---

### S3: Rainfall → runoff → stage → flood depth (P0)

**Goal:** given an hourly rainfall series, produce a flood depth grid per hour (worst-case envelope) on the 30 m grid.

**Depends on:** S2. Rain comes from S10, but test with manual rain first.

**Files:** `engines/rainfall.py`, `engines/flood.py`.

**Build in four milestones. Each one must work and be demoable before you start the next.**

- **S3.1 (M1: stage slider only).** `depth = clip(stage_m - hand, 0, None)` where `hand < 30`. Cells with `gsw_occ > 90` are permanent water: set them to `NaN` and render them as water, not flood. Wire this to a temporary endpoint, `?stage=`, and check it on the map. *This alone already makes a demo.*
- **S3.2** Runoff coefficient `C` from `lc_class` (Dynamic World indices). This is a typical rational-method table and must be **editable in config**:

  | 0 water | 1 trees | 2 grass | 3 flooded_veg | 4 crops | 5 shrub_scrub | 6 built | 7 bare | 8 snow_ice |
  |---|---|---|---|---|---|---|---|---|
  | 1.00 | 0.25 | 0.35 | 0.60 | 0.45 | 0.40 | 0.85 | 0.60 | 0.50 |

  `C_reach` = mean C over the hydro cells upstream of the reach end. For M2 use the mean over the whole grid. Clamp to `[0.10, 0.95]`.
- **S3.3** `rational_q(C, i_mm_h, A_km2) = 0.278 * C * i_mm_h * A_km2` (m³/s). Use `A = A_loc_km2` (the storm falls on the selected area).
- **S3.4** Time of concentration:
  - Kirpich (1940): `tc_min = 0.0195 * L_m**0.77 * S**-0.385`;
  - flow length from Hack's law: `L_km = 1.27 * A_loc_km2**0.6`, so `L_m = 1000 * L_km`;
  - `S` = reach slope clamped to `[0.005, 0.5]`;
  - `tc_h = tc_min / 60`.
- **S3.5 (M2: one reach).** Pick the reach with the largest `A_loc_km2`. Run the hourly envelope (S3.6) for it only, and apply its stage to every cell. Demo it.
- **S3.6 Hourly worst-case envelope algorithm.** For each reach r and hour t = 1..H, with rain series `i[1..H]` (mm/h):

  ```
  W        = clamp(round(tc_h[r]), 1, t)                 # averaging window (hours)
  i_eff    = mean(i[t-W+1 .. t])                          # mm/h
  ramp     = min(1.0, t / max(tc_h[r], 1e-6))             # rising limb until concentration time
  Q[r,t]   = rational_q(C_reach[r], i_eff, A_loc[r]) * ramp + upstream_inflow_m3s(r)
  h[r,t]   = src_stage(r, Q[r,t]) + river_offset_m
  h[r,t]   = max(h[r,t], h[r,t-1])                        # envelope: water never recedes in the scenario
  ```

  `upstream_inflow_m3s(r)` is 0 unless the scenario sets an inflow. The envelope is deliberate: it over-estimates (no recession, no routing delay), which is the safe direction for evacuation planning. Say so in the UI.
- **S3.7 (M3: per reach).** `depth[t] = clip(h[reach_id_30, t] - hand, 0, None)`, with cells where `reach_id_30 == -1` set to 0 and the permanent-water mask as in S3.1. Vectorise as `h_t_by_reach[reach_id_30]` with a lookup array, not a loop.
- **S3.8** Outputs:
  - `depth_stack` float16 `[H, rows, cols]`, saved to GCS as `runs/{run_id}/depth.npz`;
  - `flooded_area_km2[t] = count(depth[t] > 0.05) * 900 / 1e6`;
  - `stage_by_reach_m`;
  - one PNG per hour (colormap in S16.8).
- **S3.9** Hotspot linkage: attach each S2 hotspot's local depth and stage at the worst hour.

**Acceptance (unit tests, §7):**

- `rational_q(0.5, 50, 50) == 347.5`
- Kirpich `(L=10000, S=0.05)` ≈ 74.29 min
- Hack `(A=50)` ≈ 13.28 km
- toy depth grid correct
- envelope is non-decreasing

On the map, raising rain from 20 to 100 mm/h visibly enlarges the flood. A 4-hour run on a 10 km AOI computes in under 2 s.

**Pitfalls:**

- Units. `i` is mm/h, `A` is km², `Q` is m³/s, so the constant is 0.278.
- The rational method is meant for small catchments, and gives coarse upper bounds for large `A_loc`. That's why we use `A_loc` (storm over the selected area), not the whole upstream basin. Note it in Methods.

---

### S4: Flood susceptibility index, FSI (P1)

**Goal:** a static 0–1 flood susceptibility map with 5 classes, weighted by AHP.

**Depends on:** S1, S2.

**Files:** `engines/ahp.py`, `engines/fsi.py`.

**Steps:**

- **S4.1** `ahp.py`:
  - `ahp_weights(M) -> (w, lambda_max, CI, CR)` using the principal eigenvector (`numpy.linalg.eig`, take the max real eigenvalue, `abs` the vector, normalise to sum 1);
  - `CI = (λmax − n)/(n − 1)`, `CR = CI / RI[n]`;
  - `RI = {3:.58, 4:.90, 5:1.12, 6:1.24, 7:1.32, 8:1.41, 9:1.45, 10:1.49}` (Saaty);
  - raise if `CR >= 0.10`.
- **S4.2** Factor scores, each mapped to 0..1 where 1 means more susceptible. Thresholds are config values.

  | Factor | Transform |
  |---|---|
  | `hand` | `1 - min(hand/30, 1)` |
  | `gfd_count` (historical floods) | `min(gfd_count / max(1, p99(gfd_count over training box)), 1)`, OR'd with `gsw_occ/100` for seasonal water (take the max) |
  | `dist_stream_m` | `1 - min(d/1000, 1)` |
  | `upa` | `log10(1+upa) / log10(1+max_upa)` |
  | `rain_clim` | `clip((rain_clim - 50)/(300 - 50), 0, 1)` (mm/day) |
  | `slope_deg` | `1 - min(slope/30, 1)` |
  | `C` (runoff coefficient) | as-is |

- **S4.3** Default AHP matrix. Order: `[hand, hist, dist_stream, upa, rain, slope, C]`. Precomputed: **CR = 0.013**; weights ≈ `[0.236, 0.165, 0.148, 0.148, 0.135, 0.092, 0.077]`.

  ```
  hand   [1,   1,   2,   2,   2,   2,   3]
  hist   [1,   1,   1,   1,   1,   2,   2]
  dist   [1/2, 1,   1,   1,   1,   2,   2]
  upa    [1/2, 1,   1,   1,   1,   2,   2]
  rain   [1/2, 1,   1,   1,   1,   1,   2]
  slope  [1/2, 1/2, 1/2, 1/2, 1,   1,   1]
  C      [1/3, 1/2, 1/2, 1/2, 1/2, 1,   1]
  ```

  The matrix lives in config so experts can edit it. The UI's Methods page shows the weights and CR.
- **S4.4** `fsi = Σ w_k · score_k`. Classes: `<0.2` very low, `0.2–0.4` low, `0.4–0.6` moderate, `0.6–0.8` high, `≥0.8` very high.
- **S4.5** Save `fsi` and its PNG (5-class yellow→dark red).

**Acceptance:** CR test passes; high FSI sits along valley floors and confluences; Methods shows weights.

---

### S5: Landslide susceptibility, static + rainfall-modulated (P1)

**Goal:** `lsi_static` (0–1, 5 classes), with weights from AHP and class ratings from Frequency Ratio where enough past landslides exist. Plus `lsi_dyn[t]`, modulated by scenario rainfall. Shown as susceptibility, **never as a timed prediction**.

**Depends on:** S1, S2 (`dist_stream`), S7.1 (`dist_road`).

**Files:** `engines/landslide.py`, `engines/fr.py`.

**Steps:**

- **S5.1** Factor classes (bins are config values):

  | Factor | Classes |
  |---|---|
  | slope_deg | 0–15, 15–25, 25–35, 35–45, >45 |
  | rain_clim (mm/d) | quintiles over the training region |
  | ndvi | <0.2, 0.2–0.4, 0.4–0.6, >0.6 |
  | dist_stream_m (drainage) | <100, 100–300, 300–600, >600 |
  | dist_road_m | <50, 50–150, 150–300, >300 |
  | soil_clay (%) | <15, 15–30, 30–45, >45 |
  | curv | concave (<−0.5), flat, convex (>0.5) |
  | aspect | N, NE, E, SE, S, SW, W, NW, flat |

- **S5.2** Landslide inventory: NASA Global Landslide Catalog in the Earth Engine community catalog, `projects/sat-io/open-datasets/events/global_landslide_1970-2019` (FeatureCollection; **VERIFY** access and licence).
  - Training region = the AOI buffered by 50 km. This needs the same factor layers at 90 m for that larger box: fetch them with `fetch_grid` on a coarse 90 m UTM grid.
  - Drop points whose location accuracy field (if present) is worse than 10 km.
- **S5.3** Frequency Ratio (Lee & Pradhan 2007), for each factor f and class k:
  - `FR_fk = (slides_in_k / total_slides) / (cells_in_k / total_cells)`;
  - rasterise points to the 90 m grid, using a 1-cell buffer;
  - rating `r_fk = FR_fk / max_k(FR_fk)`.
  - **If `total_slides < 15`**, use the expert fallback ratings below instead and add a warning.

  | Factor | Expert fallback ratings (0–1), in class order |
  |---|---|
  | slope | 0.1, 0.4, 0.7, 1.0, 0.8 |
  | rain_clim | 0.2, 0.4, 0.6, 0.8, 1.0 |
  | ndvi | 1.0, 0.7, 0.4, 0.2 |
  | dist_drainage | 1.0, 0.7, 0.4, 0.2 |
  | dist_road | 1.0, 0.7, 0.4, 0.2 |
  | soil_clay | 0.3, 0.6, 0.9, 0.7 |
  | curvature | concave 0.8, flat 0.4, convex 0.5 |
  | aspect | N .4, NE .4, E .5, SE .6, S .6, SW .6, W .5, NW .4, flat .1 |

- **S5.4** AHP weights. Order: `[slope, rain_clim, landcover_ndvi, dist_drainage, dist_road, soil_clay, curvature, aspect]`. Precomputed: **CR = 0.010**; weights ≈ `[0.206, 0.190, 0.130, 0.107, 0.107, 0.107, 0.091, 0.063]`.

  ```
  slope  [1,   1,   2,   2,   2,   2,   2,   3]
  rain   [1,   1,   1,   2,   2,   2,   2,   3]
  ndvi   [1/2, 1,   1,   1,   1,   1,   2,   2]
  drain  [1/2, 1/2, 1,   1,   1,   1,   1,   2]
  road   [1/2, 1/2, 1,   1,   1,   1,   1,   2]
  soil   [1/2, 1/2, 1,   1,   1,   1,   1,   2]
  curv   [1/2, 1/2, 1/2, 1,   1,   1,   1,   1]
  aspect [1/3, 1/3, 1/2, 1/2, 1/2, 1/2, 1,   1]
  ```

- **S5.5** `lsi_raw = Σ w_f · r_f(class_f(cell))` on the 30 m AOI grid.
  - Min–max normalise using the **training-region** min/max, so scores are comparable across AOIs.
  - Classes 1–5 by training-region quantiles at 20/40/60/80%.
  - Mask slopes under 5°: class 1.
- **S5.6** Rainfall modulation. The trigger threshold is Caine (1980), global and configurable: `I_thr(D) = 14.82 · D^-0.39` (mm/h, D in hours). For hour t:
  - `D = t`
  - `I_mean = sum(i[1..t]) / t`
  - `R_t = I_mean / I_thr(t)`
  - `g = clip(R_t, 0.5, 1.5)`
  - `lsi_dyn[t] = clip(lsi_static × g, 0, 1)`
  - Reclassify with the same thresholds. Store the class per hour as uint8 `[H, rows, cols]`.
  - Note in Methods that India- or Uttarakhand-specific thresholds can replace Caine's global one.
- **S5.7** Outputs:
  - `lsi_static` and its PNG;
  - `lsi_dyn_class` stack, with a PNG per hour;
  - `landslide_exposed_pop[t]` (S6);
  - critical road segments (S8).

**Acceptance:**

- CR test passes.
- High classes cluster on steep, road-cut slopes.
- Rain 10 mm/h × 1 h lowers the class (g < 1). Rain 60 mm/h × 4 h raises it.
- With fewer than 15 points, the fallback is used and a warning appears.

---

### S6: Buildings, population and exposure triage (P0)

**Goal:**

- every building gets a **proxy structure class** with a confidence;
- population is distributed to buildings;
- for each hour, exposure counts and a triage table (who needs help first);
- a verification queue for field inspection.

**Depends on:** S1, S3. S5 is optional (landslide exposure).

**Files:** `engines/buildings.py`, `engines/population.py`, `engines/exposure.py`.

**Steps:**

- **S6.1 Proxy structure classification.** Rules are applied in order; the first match wins. This is a **proxy** from footprint, height and density only: label it "likely …", never as fact.

  | Rule | Class | Fragility F | Confidence |
  |---|---|---|---|
  | `height_m` missing and `area_m2 < 25` | `makeshift_or_hut` | 1.0 | 0.35 |
  | `height_m < 3.5` and `area_m2 < 40` | `makeshift_or_hut` | 1.0 | 0.50 |
  | cluster rule (S6.2) true | `informal_cluster` (chawl / basti-like) | 0.75 | 0.45 |
  | `height_m < 4.5` and `area_m2 < 120` | `likely_kaccha_or_low_rise` | 0.80 | 0.40 |
  | `presence_2016 < 0.3` and `presence_2023 >= 0.5` and `height_m < 4.5` | `new_unplanned_low_rise` | 0.80 | 0.35 |
  | `height_m >= 6.5` | `likely_pukka_multi_storey` | 0.20 | 0.55 |
  | otherwise | `likely_pukka_low_rise` | 0.45 | 0.40 |

  `floors = max(1, round(height_m / 3.2))`, with 1 if the height is missing.
- **S6.2** Cluster rule: with a KD-tree on centroids, count buildings within 30 m. True if `count >= 8` and the local mean area is below 60 m².
- **S6.3** Field-verified override (from S12): if a building has a photo classification with `confidence >= 0.6`, replace class and F, and set `source="field_photo"`.
- **S6.4 Population to buildings.**
  1. For each 30 m cell, find buildings whose centroid falls in it.
  2. Building volume `vol = area_m2 × max(height_m or 3, 3)`.
  3. `pop_b = pop30[cell] × vol / Σvol_cell`.
  4. Cells with population but no buildings keep it as `pop_unattributed[cell]`.
  5. Apply `pop_multiplier`. If `pop_total_override` is set, rescale every value by `override / current_total`.
  6. Check: sum of buildings + unattributed equals the scaled total.
- **S6.5** Per-hour exposure:
  - building depth `d_b[t] = depth[t][row(centroid), col(centroid)]`;
  - building landslide class `ls_b[t] = lsi_dyn_class[t][…]`;
  - grid population exposure uses `pop_unattributed` with the depth grid.
- **S6.6** Building risk score at the evaluation hour (default: the worst hour, H):
  - `D = min(d_b / 3.0, 1)`
  - `P = 1 − min(dist_stream_m / 300, 1)`
  - `R_b = 0.5·D + 0.3·F + 0.2·P`, and `R_b = 0` if `d_b < 0.05` **and** `ls_b <= 3`
  - Risk classes: `≥0.7` critical, `0.5–0.7` high, `0.3–0.5` moderate, `<0.3` low.
  - A building with `ls_b >= 4` is raised to at least "high" and gets the reason `landslide`.
- **S6.7** `ExposureSummary`:

  ```python
  class ExposureSummary(BaseModel):
      total_pop: int
      exposed_pop_by_hour: list[int]                 # depth ≥ 0.05 m
      exposed_by_depth_band: dict[str, int]          # "0.05-0.5","0.5-1.5",">1.5" at worst hour
      landslide_exposed_pop_by_hour: list[int]       # lsi_dyn class ≥ 4
      buildings_by_risk: dict[str, int]
      clusters: list[dict]   # id "C1".., centroid, people, max_depth, dominant_class, risk
  ```

  Clusters: aggregate exposed buildings plus grid population into 300 m cells. Keep the top 20 by people × risk.
- **S6.8** `TriageRow = {structure_class, risk_class, buildings, people}` at the worst hour. Sort by risk, then people.
- **S6.9** Verification queue: `score = R_b × (1 − confidence) × pop_b`. Return the top 50 with id, location and current class. "Go and check these first" is a strong decision-support output.

**Acceptance:**

- The population sum is conserved.
- On a toy fixture, building risk matches hand-computed values.
- Raising rain raises exposed population monotonically.
- Triage renders.

**Pitfalls:**

- Open Buildings heights are model estimates (range 0–100 m), so treat them as approximate.
- WorldPop is residential and night-time-like. Note "day/night blindness" as a limitation.
- Do not mention caste, religion or any group attribute. Classify **structures**, never people.

---

### S7: Roads, shelters and staging points (P0)

**Goal:** graphs ready for routing with per-edge sampling indices and static attributes, plus a shelter list with capacities.

**Depends on:** S1, S5 (static LSI).

**Files:** `engines/roads.py`, `engines/shelters.py`.

**Steps:**

- **S7.1** Load `G_walk`/`G_drive` and project them to the grid CRS (`ox.project_graph`, **VERIFY** in 2.x). Use the `travel_mode` graph per run.
- **S7.2** For every edge, sample points every 30 m along its geometry (or a straight line between the nodes). Store `edge_cells: int32 flat indices`, and the `bridge` flag (`True` when the OSM `bridge` tag is truthy and not "no").
- **S7.3** Travel time:
  - **walk** uses Tobler's hiking function (1993), `v_kmh = 6 · exp(−3.5 · |tanθ + 0.05|)` with `tanθ = (dem_end − dem_start)/length`. It is direction-specific (the graph is directed).
  - **drive** uses OSMnx speed imputation (`add_edge_speeds` and `add_edge_travel_times`; **VERIFY** the 2.x module path).
  - Store `t0_s` per edge.
- **S7.4** Static edge attributes:
  - `lsi_static_max` along the edge;
  - `slope_adjacent = max(slope_deg in a 3×3 window around the sample cells) >= 35`;
  - `highway`, `lanes`, `width` (S9).
- **S7.5** Shelter candidates from OSM POIs:
  - `amenity ∈ {school, college, university, community_centre, townhall, social_facility}`;
  - `place_of_worship` is included but flagged "large hall, confirm with authority".
  - **Medical facilities** (`amenity ∈ {hospital, clinic}`) are a separate list. They are staging and medical destinations, not general shelters.
- **S7.6** Shelter capacity:
  - footprint = the OSM polygon if present, else the nearest Open Buildings polygon within 30 m, else 200 m² with `capacity_confidence="low"`;
  - `floors` from the matched Open Buildings height (S6.1);
  - `capacity = floor(area_m2 × floors × 0.6 / sqm_per_person)`; the default 3.5 m² is the Sphere minimum covered space per person;
  - snap to the nearest graph node;
  - store `{id: "S1".., name, lon, lat, node, area_m2, floors, capacity, capacity_confidence, hand_m, lsi_class, primary: inside AOI?}`.
- **S7.7** Temporary assembly points (computed per run in S8.4):
  - `scipy.ndimage.label` on the mask `max_depth==0 & hand>=10 & slope_deg<=10 & lsi_static_class<=2 & dist_road_m<=150`;
  - keep components of at least 1,000 m²;
  - `capacity = floor(area × 0.5 / 2.0)`;
  - label "temporary open-air assembly point" and keep the top 10 by capacity.
- **S7.8** Staging-point candidates (for the advisory): dry, flat cells within 100 m of a `drive` road that stays passable for the whole scenario, near the highest-exposure clusters. Output up to 5 with the reason "ambulance/police/medical staging".

**Acceptance:**

- Shelters appear on the map with capacities.
- A walk route between two nodes gives a plausible time (around 4–5 km/h on flat ground).
- Bridges are flagged where OSM has them.

**Pitfalls:**

- OSM coverage in hill towns can be thin. Let the user add shelters (S16) and surface "few shelters found" as a warning and an advisory item.

---

### S8: Evacuation routing with capacity-aware assignment (P0)

**Goal:**

- people are assigned to reachable shelters within capacity, by minimum total travel time, on the **flood- and landslide-adjusted** network;
- capacity shortfalls are flagged and assembly points suggested;
- every route has a "passable until hour X" stamp.

**Depends on:** S3, S5, S6, S7, S9.

**Files:** `engines/routing.py`.

**Steps:**

- **S8.1** Per-edge state for every hour t:
  - `edge_depth[t] = max(depth[t][edge_cells])`;
  - `edge_lsi[t] = max(lsi_dyn_class[t][edge_cells])`.

  An edge is **closed** at t if any of these hold:
  - depth exceeds `walk_depth_limit_m` / `vehicle_depth_limit_m`;
  - it's a bridge and either `edge_depth > 0` or any reach whose cells the bridge crosses has stage ≥ `bridge_cut_stage_m`;
  - `edge_lsi == 5`;
  - it intersects any `blocked_polygons`.

  `first_closed_hour[e]` = the first t that closes it (∞ if never), with a reason (`flood`, `bridge`, `landslide` or `blocked`).
- **S8.2** Edge cost at the evaluation hour `t_eval = min(H, evac_start_hour + 1)` (conservative):
  - `w = t0_s × (1.5 if edge_lsi==4 else 1.2 if edge_lsi==3 else 1.0) × (1 + 0.3 × crowd_e) × (1.2 if slope_adjacent else 1.0)`;
  - remove edges closed at `t_eval`, giving `G_eval`.
- **S8.3** Demand:
  - every building with `d_b > 0.05` at any hour, or `ls_b >= 4` at any hour, plus exposed unattributed grid population;
  - snap each to its nearest node and sum people per node;
  - `demand[node] = ceil(people)`.
- **S8.4** Supply:
  - shelters (S7.6) minus `disabled_shelter_ids`, plus `extra_shelters`, plus assembly points (S7.7);
  - a shelter is **usable** only if its max depth over all hours is 0, its `lsi_dyn` class ≤ 3 at every hour, and its node is in `G_eval`.
- **S8.5** Travel times: for each usable shelter s, run `nx.single_source_dijkstra_path_length(G_eval.reverse(copy=False), s.node, weight="w", cutoff=max_travel_min*60)`. This gives the time from every node to s.
- **S8.6** Transportation problem, solved with `nx.network_simplex`. All demands and weights must be integers.

  ```
  nodes:  D:<node> (demand = -people), S:<id> (demand 0), T (demand = +total_people)
  edges:  D:<node> → S:<id>   weight = int(seconds), only if reachable within cutoff
          S:<id>   → T        capacity = shelter.capacity, weight = 0
          D:<node> → T        weight = 10_000_000          # "unplaced" overflow, always feasible
  ```

- **S8.7** Read the flows:
  - allocation `flow[D][S]`;
  - **capacity gap** = `Σ flow[D][T]`.
  - For each `(D, S)` with flow > 0, the path is `nx.shortest_path(G_eval, D.node, S.node, weight="w")`. Record `eta_min`, `people`, `passable_until_h = min(first_closed_hour over path edges)`, and `use_now_gone_soon = passable_until_h <= evac_start_hour + 2`.
- **S8.8** If the capacity gap is above 0:
  - mark the clusters left unplaced;
  - list the nearest assembly points with spare capacity;
  - add the warning "Capacity gap: N people have no reachable shelter in this scenario. Consider external transport or additional shelters."
- **S8.9** Bridge table: `{id, name, first_closed_hour, reason}`, which drives "close bridge X before hour Y".
- **S8.10** GeoJSON outputs (WGS84):
  - roads with `first_closed_hour` and `reason`;
  - routes with `people`, `eta_min`, `passable_until_h`, `to_shelter`, `from_cluster`;
  - shelters with `capacity`, `assigned`, `spare` and `status` (usable, flooded, landslide_risk, disabled or unreachable).

**Acceptance (unit tests, §7):**

- The toy transportation problem gives cost 760 and the expected allocation.
- The overflow toy gives a gap of 30.

On the map:

- closing a shelter in the UI reroutes people and the gap number changes;
- drawing a block polygon over a bridge reroutes around it.

**Pitfalls:**

- `network_simplex` needs integer weights and demands.
- Make sure total supply is at least total demand by keeping the overflow edge, or the solver raises.

---

### S9: Crowding and evacuation-difficulty index (P1)

**Goal:** mark places and road segments that are **typically crowded** or **hard to evacuate**, using open data only. This complies with §2.2.

**Depends on:** S1, S7.

**Files:** `engines/crowding.py`.

**Steps:**

- **S9.1** POI attractor weights (config):

  | Attractor | Weight |
  |---|---|
  | `amenity=marketplace` | 1.0 |
  | `amenity=bus_station`, `public_transport=station`, `railway=station` | 1.0 |
  | `amenity=place_of_worship` | 0.8 (yatra/pilgrim crowds) |
  | `tourism ∈ {hotel, guest_house, hostel}` | 0.6 (visitors unfamiliar with routes) |
  | `amenity ∈ {school, college, hospital}` | 0.6 |
  | `shop=*` | 0.2 |

- **S9.2** Grid crowding:
  1. Rasterise POI weights to 30 m.
  2. Add `0.5 ×` the building count per cell (from S6).
  3. Apply `scipy.ndimage.gaussian_filter(sigma = 100 m / 30 m)`.
  4. Normalise to 0..1, clipping at the 99th percentile. Save as `crowd`.
- **S9.3** Edge narrowness from the `highway` class:
  - footway/path/steps 1.0
  - living_street/service 0.8
  - residential/unclassified 0.6
  - tertiary 0.4
  - secondary 0.3
  - primary/trunk 0.2
  - subtract 0.1 if `lanes >= 2` or `width >= 7 m`, and clamp to 0..1.
- **S9.4** `crowd_e = 0.6 × max(crowd along edge) + 0.4 × narrowness`.
- **S9.5** Outputs:
  - the `crowd` PNG;
  - top 10 crowding hotspots `{id: "X1".., lon, lat, score, top_attractors}`;
  - `crowd_e` on edges, used by S8.
- **S9.6** In the frontend, the **Maps Traffic Layer** toggle is for humans to see live traffic. Its data is never read into the engine.

**Acceptance:** markets, bus stands and temple areas rank high, and narrow lanes score high.

---

### S10: Forecast and scenario builder (P1)

**Goal:**

- a 10-day forecast strip with the worst day highlighted;
- rain series for forecast, worst, best, historical-extreme and manual scenarios;
- a past-90-days rainfall chart.

**Depends on:** S1. S3 uses the result.

**Files:** `services/weather.py`, `engines/rainfall.py` (series builders), `api/forecast.py`.

**Steps:**

- **S10.1** `ForecastProvider` interface: `hourly(lat, lng, hours) -> list[{time, precip_mm}]`, `daily(lat, lng, days) -> list[{date, precip_mm}]`, `alerts(lat, lng) -> list`.
- **S10.2** `GoogleWeatherProvider` (default), using the Maps Platform Weather API at base `https://weather.googleapis.com`:
  - `GET /v1/forecast/hours:lookup` (up to 240 h);
  - `GET /v1/forecast/days:lookup` (up to 10 days);
  - `GET /v1/publicAlerts:lookup`.
  - Pass `key`, `location.latitude` and `location.longitude`, and handle pagination (`pageSize`/`pageToken`).
  - **VERIFY** parameter names and the precipitation field path (likely `precipitation.qpf.quantity` in mm) against the discovery doc at `https://weather.googleapis.com/$discovery/rest?version=v1`.
- **S10.3** `IMDProvider`: **optional**, behind `FORECAST_PROVIDER=imd`. It is non-Google official data and is only used if a stable IMD endpoint is available. **DECISION**: build it only if the human confirms access. The Methods page cites IMD as the production source for India regardless.
- **S10.4** Caching: keep forecast responses **in memory for 10 minutes only**. Don't persist raw Weather API responses (Maps terms §3.2.3(b)). A run stores the scenario label and the series it used, for reproducibility. **VERIFY** the Weather API service-specific caching terms. If storing the series isn't allowed, store only the label and refetch.
- **S10.5** Series builders, each returning `list[float]` of length `duration_h`, in mm/h:
  - `forecast`:
    1. Choose the day (`forecast_day_index`, or the max daily total).
    2. Take that day's 24 hourly values.
    3. Pick the **wettest window** of `duration_h` consecutive hours (sliding sum).
  - `worst`: forecast × `worst_multiplier`. `best`: forecast × `best_multiplier`.
  - `historical_extreme`:
    1. Get the max daily CHIRPS total over 2001–2024 within 5 km of the AOI centroid: `UCSB-CHG/CHIRPS/DAILY` `.max()` reduced with `reduceRegion(max)`.
    2. Distribute it over `duration_h` using the hyetograph.
  - `manual`:
    - `constant`: `[intensity] * duration_h`;
    - `triangular_front`: the peak at hour `ceil(duration_h/3)`, linear up and down, scaled so the total equals `intensity × duration_h`.
  - Always produce a human label, e.g. "Forecast Thu 16 Oct, wettest 4 h, worst case ×1.5".
- **S10.6** 10-day screening strip: for each day, run S3-M2 (one reach) on that day's wettest `duration_h` window. Badge each day: max stage `< 1 m` low, `1–3 m` elevated, `≥ 3 m` high. Label "screening, run the full scenario for details".
- **S10.7** Past 90 days: daily totals from `NASA/GPM_L3/IMERG_V07` (`precipitation` is mm/h half-hourly, so daily total = sum × 0.5). Mean over a 5 km buffer at the centroid. Build it as **one** `ee.List.sequence` mapped server-side, then one `getInfo`.
- **S10.8** `GET /api/forecast` returns `{hourly, daily, alerts, worst_day_index, past_90d, provider}`.

**Acceptance:**

- The strip shows 10 days.
- Choosing "Worst" multiplies the forecast by exactly `worst_multiplier`.
- The manual triangular series sums to `intensity × duration`.
- The past-90-days chart renders.

---

### S11: Historical incidents layer (P1)

**Goal:** before any physics runs, show **where disasters happened before**, as a red heat map, clearly labelled "historical incidents" and kept separate from modelled risk.

**Depends on:** S0. The AOI part depends on S1 and S4.

**Files:** `api/history.py`, `services/earth_engine.py`, `agents/historian.py`.

**Steps:**

- **S11.1** India-wide flood heat:
  - `ee.ImageCollection('GLOBAL_FLOOD_DB/MODIS_EVENTS/V1').select('flooded').sum().selfMask()`, visualised with a 1→10+ events palette;
  - `getMapId()` gives a tile URL template, which the frontend shows as an `ImageMapType` overlay;
  - refresh the URL on page load, since tokens expire;
  - label "Observed floods 2000–2018 (Global Flood Database, MODIS)".
- **S11.2** India landslides: the GLC FeatureCollection filtered to India bounds, exported as GeoJSON points and shown as a deck.gl `HeatmapLayer` plus points at high zoom. Label "Reported landslides 1970–2019 (NASA GLC)".
- **S11.3** AOI event table: for each GFD image intersecting the AOI, report:
  - whether any flooded pixel falls in the AOI (`reduceRegion(max)`);
  - event dates and cause properties (**VERIFY** property names, e.g. `began`, `ended`, `dfo_main_cause`);
  - plus the GLC points inside the AOI.
- **S11.4** Grounded web incidents (`historian` agent): an ADK `LlmAgent` whose **only** tool is the built-in `google_search` (**VERIFY** ADK's rule on combining built-in tools with others; keep it in its own agent).
  - Prompt: *"List documented floods, flash floods, cloudbursts and landslides affecting {place} ({bbox}) since 2000. Return JSON: [{type, date, place, summary, source_urls}]. Only include events with a source URL. If unsure of the date, say 'approximate'."*
  - Parse it, geocode `place` with the Geocoding API for **display markers only**, and store the result in `history_cache/{aoi_id}` with the sources.
  - Show Google Search attribution/suggestions as the Grounding terms require (**VERIFY**).
  - UI label: "From web sources, unverified leads".
- **S11.5** Agreement badge (credibility):
  - `overlap = |GFD_any ∩ FSI≥0.6| / |GFD_any|` inside the AOI;
  - show "X% of historically flooded cells fall in our high-susceptibility zones";
  - hide it if `GFD_any` is empty.

**Acceptance:**

- The India map shows red hotspots, including Assam, Bihar, Odisha and the Uttarakhand valleys.
- The AOI panel lists events with sources.
- The web incidents section shows source links.

---

### S12: Field photo verification with Gemini vision (P1)

**Goal:** authorities upload **their own** field or drone photos. Gemini classifies the building structure or the drain condition with a confidence, and the result overrides the proxy class. This is compliant (no Maps imagery) and realistic, because field teams already take photos.

**Depends on:** S6.

**Files:** `api/photos.py`, `services/gemini.py`, `models/photo.py`.

**Steps:**

- **S12.1** `POST /api/photos` (multipart): store the image at `gs://…/photos/{aoi_id}/{photo_id}.jpg`. Read EXIF GPS with Pillow; if it's missing, require `lat`/`lng` from the UI pin.
- **S12.2** Schemas:

  ```python
  class BuildingPhotoResult(BaseModel):
      building_visible: bool
      structure_class: Literal["pukka_multi_storey","pukka_low_rise","kaccha","makeshift_or_hut","informal_cluster","unclear"]
      wall_material: Literal["rcc_or_brick_cement","brick_mud","stone_mud","wood","tin_or_sheet","tarpaulin_or_plastic","mixed","unclear"]
      roof_material: Literal["rcc_slab","tin_or_sheet","tile","thatch","tarpaulin","unclear"]
      storeys_estimate: int | None
      visible_risk_notes: list[str]      # e.g. "built on slope edge", "next to stream bank"
      confidence: float                  # 0..1
      rationale: str                     # ≤ 40 words
  class DrainPhotoResult(BaseModel):
      drain_visible: bool
      condition: Literal["clear","partially_blocked","blocked","unclear"]
      blockage_types: list[Literal["garbage","silt","vegetation","construction_debris","other"]]
      confidence: float
      rationale: str
  ```

- **S12.3** Gemini call: `GEMINI_MODEL_FAST`, an image part plus the prompt below, `response_mime_type="application/json"`, `response_schema=<Model>`, temperature 0.1.

  > *You are assisting a disaster-management engineer with a rapid visual survey. Look only at the structure (or drain) in this photo. Classify it using the schema. If the view is unclear, use "unclear" and a low confidence. Do not describe or infer anything about people. This is a first-pass triage for field verification, not a structural assessment.*

- **S12.4** Link the result:
  - nearest Open Buildings polygon within 20 m (building), or nearest OSM waterway/culvert within 30 m (drain);
  - save to `photos/{photo_id}` with `linked_bid` / `linked_drain_id`;
  - S6.3 and S13.3 read these on the next run.
- **S12.5** Reject results where `building_visible == false` or `drain_visible == false`, and tell the user.
- **S12.6** Demo data, **DECISION**: the owner's own photos (e.g. Mumbai buildings and nalas taken by him) or openly licensed images with attribution. Avoid identifiable faces.

**Acceptance:**

- Uploading a clear photo of a tin-roof hut returns `makeshift_or_hut`/`tin_or_sheet` with confidence ≥ 0.6, and the linked building's class changes on the next run.
- A blurry photo returns "unclear".

---

### S13: Urban mode, Mumbai (P2)

**Goal:** for city AOIs (`mode="urban"`), give a **pluvial ponding screening** and a **drain/culvert inspection priority list** for pre-monsoon clearing. It is labelled as screening, not hydrodynamic modelling.

**Depends on:** S1, S6. S12 is optional.

**Files:** `engines/pluvial.py`, `engines/drains.py`.

**Steps:**

- **S13.1** Priority-flood depression filling (Barnes et al. 2014, with an epsilon variant so flats drain): a `heapq` over boundary cells gives `filled`. Then `dep_depth = filled − dem`.
- **S13.2** D8 on `filled` (30 m) for steepest descent, then accumulation reusing the S2.3 topological routine. Label depressions with `scipy.ndimage.label(dep_depth > 0.05)`.
  - For each depression: `V_dep = Σ dep_depth × 900`.
  - `A_ws` = cells whose flow path ends in the depression (trace as in S2.5).
- **S13.3** For each depression:
  - `V_in = C_mean × (Σ rain mm / 1000) × A_ws_m2`
  - `fill = min(1, V_in / V_dep)`
  - `ponding_depth = dep_depth × fill`
  - Output a "ponding likelihood" map (low, med, high by fill ≥ 0.3, ≥ 0.7).
- **S13.4** Drain points:
  - OSM waterways (`drain`, `canal`, `ditch`, `stream`), culverts (`tunnel=culvert`) and waterway × road intersections;
  - `priority = 0.4·norm(log accumulation) + 0.3·max(fsi, ponding) + 0.3·norm(exposed pop within 300 m)`;
  - a field photo marked `blocked` adds +0.3, and `clear` subtracts 0.2;
  - output the top 20 `{id: "D1".., lon, lat, type, priority, photo_condition?}`.
- **S13.5** These feed the advisory's **seasonal** horizon: "Inspect and clear drain D3 before monsoon".

**Acceptance:**

- On a Mumbai AOI, known low-lying areas show a high ponding likelihood (a sanity check against news reports, not a calibration).
- The drain list renders with priorities.

**Pitfalls:** Copernicus GLO-30 is a **surface** model that includes buildings. In dense cities this distorts ponding, so state it prominently in Methods.

---

### S14: Orchestration brain (Google ADK) (P0)

**Goal:**

- a deterministic pipeline that does the computing;
- Gemini agents that convert natural language into parameters, answer follow-ups by running tools, and fetch historical leads.

*Gemini conducts and narrates; engines compute.*

**Depends on:** S3–S10.

**Files:** `pipeline/run_pipeline.py`, `agents/*.py`, `api/runs.py`, `api/chat.py`, `api/plan.py`.

**Steps:**

- **S14.1** `run_pipeline(params) -> RunResult` runs in a **fixed order**:
  1. load static layers;
  2. S10 series;
  3. S3 depth stack;
  4. S5 dynamic LSI;
  5. S6 exposure;
  6. S7.7 assembly points;
  7. S8 routing;
  8. render PNGs and GeoJSON;
  9. save to Firestore and GCS.

  Log the timing per step. Collect warnings. This function **never** calls Gemini.
- **S14.2** `agents/tools.py`: plain Python functions with type hints and docstrings (ADK wraps them as FunctionTools). **Each returns a compact dict under 4 KB** with ids and numbers only, never arrays:
  - `get_forecast_summary(aoi_id)`
  - `run_scenario(aoi_id, overrides: dict)`: merges with the current params, validates with pydantic, runs, and returns summary + `run_id`
  - `get_run_summary(run_id)`
  - `compare_runs(run_id_a, run_id_b)`
  - `list_shelters(run_id)`, `list_bridges(run_id)`, `list_closed_roads(run_id, hour)`
  - `find_shelter_by_name(aoi_id, name)`: fuzzy match, returns the id
  - `get_historical_summary(aoi_id)`
- **S14.3** `scenario_planner`: `LlmAgent(model=GEMINI_MODEL_FAST, output_schema=ScenarioParams)`. With `output_schema` set the agent cannot use tools, which is fine. Its input includes the user text, the current params, the forecast summary and the shelter names with ids. Instruction:

  > *Convert the official's request into ScenarioParams. Only change fields the request mentions. Map shelter names to ids from the provided list. Keep values within allowed ranges. If the request is ambiguous, keep current values. Output only the schema.*

  The API returns the params **and a diff** to the UI. The human clicks Apply (human-in-the-loop) before the run starts.
- **S14.4** `analyst`: `LlmAgent(model=GEMINI_MODEL_FAST, tools=[the tools from S14.2])`. Instruction:

  > *You help district officials explore flood and landslide scenarios. Never state a number you did not get from a tool result. For what-if questions, call run_scenario with only the changed fields, then compare_runs against the previous run. Cite ids (shelters S…, bridges B…, clusters C…). Use the words estimated, susceptibility, suggested. End substantive answers with: "Decision-support draft for official review."*

- **S14.5** `historian`: S11.4.
- **S14.6** Wire it up with ADK `Runner` + `InMemorySessionService`. Use one session per browser tab, keyed by `session_id`. `POST /api/chat` runs the analyst and returns `{reply, new_run_id?}`, where `new_run_id` is set if `run_scenario` was called.
- **S14.7** Optional showcase: an ADK `SequentialAgent` named `full_assessment` with sub-agents `scenario_planner` → a custom `BaseAgent` that calls `run_pipeline` → `advisor` (S15). Expose it at `POST /api/assess`. The main UI still uses the explicit endpoints, for reliability.
- **S14.8** Vertex AI configuration: `google-genai` with `vertexai=True` (env `GOOGLE_GENAI_USE_VERTEXAI=TRUE`), so usage bills to the project and its credit. **VERIFY** the model's location (`global` vs regional).

**Acceptance:**

- `/api/plan` with "What if it rains 80 mm an hour for 3 hours and the main school shelter is closed?" returns `rain_source=manual, manual_intensity_mm_h=80, duration_h=3, disabled_shelter_ids=[<school id>]`.
- Chat "Which bridge closes first?" calls `list_bridges` and cites B-ids.

---

### S15: Advisory layer (P0)

**Goal:** after each run, a prioritised, plain-language action brief across three horizons. Every recommendation is tied to evidence ids, validated, and replaced by a rules-based brief if Gemini fails.

**Depends on:** S14.

**Files:** `pipeline/facts.py`, `agents/advisor.py`, `api/runs.py`.

**Steps:**

- **S15.1** `build_facts(run) -> dict` (deterministic, at most about 12 KB). Every item carries an id:
  - `scenario` {label, H, worst_hour}
  - `key_numbers` K1…: peak exposed people, critical buildings, capacity gap, bridges closing, flooded km² at worst hour, landslide-exposed people
  - `clusters` C1… (people, max depth, dominant class, risk)
  - `shelters` S1… (capacity, assigned, spare, status)
  - `bridges` B1… (first_closed_hour)
  - `closed_roads` R1… (top 15 by length: name, hour, reason)
  - `routes` (from, to, people, eta, passable_until, use_now_gone_soon)
  - `assembly_points` A1…, `staging_points` G1…, `medical` M1…, `hotspots` H1…
  - `landslide_roads` L1… (segments with `lsi_dyn` ≥ 4)
  - `crowding` X1… (hotspots from S9.5)
  - `drains` D1… (urban), `verification_queue` V1… (top 10)
  - `forecast` {worst_day, max_daily_mm}
  - `history` {gfd_events, landslides, agreement_pct}
  - `warnings`
- **S15.2** `advisor`: `GEMINI_MODEL_PRO` via `google-genai` `generate_content` with `response_mime_type="application/json"`, `response_schema=Advisory`, temperature 0.2. Prompt:

  > *You are drafting a decision-support brief for district disaster-management officials. Use ONLY the facts JSON. Produce 6–12 recommendations across three horizons: immediate (incoming storm: who moves first, routes, shelters to open, bridges to close, where to stage ambulances/police/medical teams), seasonal (pre-monsoon: drains to clear, roads/slopes to inspect, shelters to stock), structural (long-term: where permanent shelters/medical facilities or better evacuation roads are justified). Each recommendation must list evidence_ids that exist in the facts and a 'why' that quotes numbers from those facts. Do not invent numbers, places or ids. Priority P1 = life-safety within the scenario window. Include 3–5 limitations. Use the exact disclaimer provided.*

- **S15.3** Validator:
  1. Drop any recommendation whose `evidence_ids` are not all in the facts.
  2. Extract the numbers in `why` with a regex. If one doesn't appear in the cited facts (±1% or ±1 unit), drop the recommendation and log it.
  3. Ensure each horizon has at least one recommendation, otherwise fill from S15.4.
  4. Force the `disclaimer` to the exact §2.4 string.
- **S15.4** `rules_advisory(facts)` deterministic fallback, used when Gemini errors or the validator empties a horizon:
  - **Immediate:**
    - bridges with `first_closed_hour ≤ H`: "Close {bridge} before hour {h−1}" (P1);
    - capacity gap > 0: "Arrange external transport/additional shelter for {gap} people" (P1);
    - the top 3 clusters: "Evacuate {C} ({people}) to {S} via suggested route (ETA {eta} min)" (P1/P2);
    - staging points: "Pre-position ambulance/police at {G}" (P2).
  - **Seasonal:** top drains (urban); landslide roads: "Inspect slope protection on {L}"; shelters with `assigned > 0`: "Stock {S} for {assigned} people" (P2).
  - **Structural:** the largest assembly points on high ground: "Consider a permanent shelter near {A}"; clusters with a gap: "Improve evacuation access for {C}" (P3).
- **S15.5** `POST /api/runs/{id}/advisory` generates it (or returns the cached one), stores it at `advisories/{id}` and sets `generated_by`.

**Acceptance:**

- Unit test: the validator drops a recommendation citing the unknown id `S99`.
- Forcing a Gemini error yields `rules_fallback` with all three horizons.

---

### S16: Frontend (P0 for Explore + Workspace + Advisory; P1 for the rest)

**Goal:** an intuitive, visual what-if tool for both officials and technical judges.

**Depends on:** the backend endpoints.

**Steps:**

- **S16.1** Base setup:
  - Vite + React + TS; `@vis.gl/react-google-maps` `<APIProvider apiKey>` + `<Map mapId>`;
  - a `useDeckOverlay` hook that attaches `GoogleMapsOverlay` from `@deck.gl/google-maps`;
  - typed API client in `api/client.ts`;
  - a global `<Disclaimer/>` banner.
- **S16.2** Routes:
  - `/` Explore
  - `/area/:aoiId` Workspace
  - `/area/:aoiId/run/:runId/advisory`
  - `/area/:aoiId/verify`
  - `/methods`
  - `/area/:aoiId/3d` (OPT)
- **S16.3** **Explore page:**
  - India view (centre 22.5, 79; zoom 5) with a satellite/hybrid toggle;
  - history overlays (S11.1 tiles, S11.2 heat);
  - a legend "Historical incidents, not predictions";
  - a search box (backend geocoding);
  - **Terra Draw** rectangle tool via its Google Maps adapter (the Drawing Library is gone);
  - on finish: size check (river ≤ 15 km, urban ≤ 4 km), a modal for name + mode, then `POST /api/aoi` and navigate to the Workspace with a progress bar that polls `/status`.
- **S16.4** **Workspace layout:**
  - top: `ForecastStrip` (10 days with badges, plus a past-90-days mini chart);
  - left: `LayerPanel`;
  - centre: the map;
  - right: `ScenarioPanel` with `Results` below it;
  - bottom: `TimeSlider` (hours 1..H, with play/pause);
  - the disclaimer banner is always visible.
- **S16.5** `LayerPanel` toggles, each with a legend:
  - Historical incidents
  - Flood susceptibility (FSI)
  - Height above drainage (HAND)
  - Streams & convergence hotspots
  - **Flood depth (hour t)**
  - Landslide susceptibility (static / hour t)
  - Population
  - Buildings by risk
  - Roads status
  - Bridges
  - Shelters (capacity bars)
  - Assembly points
  - Medical & staging
  - **Evacuation routes**
  - Crowding
  - Drains (urban)
  - Live traffic (Maps Traffic Layer, display only)
  - Street View (pegman, human viewing only)
- **S16.6** `ScenarioPanel` controls bind 1:1 to `ScenarioParams`:
  - rain source (segmented control);
  - day picker, synced with the strip;
  - intensity slider 5–150 mm/h (manual);
  - duration 1–24 h;
  - hyetograph;
  - river offset −1…+5 m;
  - population multiplier 0.5–2 and a total override;
  - walk/drive;
  - evacuation start hour;
  - **Advanced** (collapsed): depth limits, bridge cut stage, Manning n, m²/person, max travel minutes;
  - **Shelters list**: toggle on/off, plus "Add shelter" (click the map, enter capacity);
  - **Block road**: draw a polygon (Terra Draw), shown as removable chips;
  - **"Describe a scenario"** text box: `/api/plan` → show the param diff → Apply;
  - **Run** button;
  - run history with "Compare to previous".
- **S16.7** `Results`:
  - cards: peak exposed people, critical buildings, capacity gap (red if > 0), bridges closing, routes. Each card has a "?" tooltip in plain language;
  - `TriageTable`;
  - `ShelterList` (capacity vs assigned bar, status chip);
  - `RouteList` (ETA, "passable until hour X", a "use now" badge);
  - two small line charts: flooded km² by hour and exposed people by hour (labelled axes, units);
  - a "View advisory brief" button.
- **S16.8** Colours (accessible, legends always shown, never colour alone):
  - **flood depth**, sequential blues in 5 bins at 0.05/0.5/1/1.5/3 m: `#c6dbef #9ecae1 #6baed6 #3182bd #08519c`;
  - **susceptibility**, 5 classes: `#ffffb2 #fecc5c #fd8d3c #f03b20 #bd0026`;
  - **roads**: open grey, closes-later orange, closed red dashed with a reason icon;
  - **routes**: teal, width scaled by people;
  - **shelters**: icon, with fill showing utilisation.
  - Test on both satellite and roadmap base maps.
- **S16.9** **Advisory page:**
  - headline and key numbers;
  - tabs for Immediate / Seasonal / Structural;
  - cards with a priority chip, action, location (click to fly there on the map), why, evidence chips and confidence;
  - limitations, the disclaimer, and a "Generated by Gemini / Rules fallback" tag;
  - a **Print / Save as PDF** button (print CSS).
- **S16.10** **Verify page:** a verification queue (list + map), `PhotoUploader` (kind, auto-GPS or pin), result cards, and "Applied on next run".
- **S16.11** **Methods page:** a plain-language explanation of each model (with a small diagram), the formulas, the AHP tables with CR, assumptions, **limitations (§8)**, and **data sources with licences and attributions**:
  - "© OpenStreetMap contributors (ODbL)"
  - Open Buildings CC-BY 4.0
  - MERIT Hydro CC-BY-NC 4.0
  - GFD CC-BY-NC 4.0
  - WorldPop, CHIRPS, GPM IMERG, Dynamic World, Copernicus DEM, JRC GSW, NASA GLC (**VERIFY** each licence string)
- **S16.12** `ChatPanel`: a slide-over that shows "running scenario…" while tools run. When `new_run_id` comes back, load that run and highlight what changed.
- **S16.13** Empty, loading and error states everywhere. Desktop-first; at 1280 px wide there should be no horizontal scroll.

**Acceptance:** the full loop works on the deployed URL: draw → prepare → run → slide hours → close a shelter → re-run → advisory → print.

---

### S17: Deployment (P0)

- **S17.1** Backend: `gcloud run deploy pravah-backend --source backend --region asia-south1 …` with the flags from S0.12 and secrets from Secret Manager (`--set-secrets MAPS_SERVER_KEY=maps-server-key:latest`).
- **S17.2** Frontend: `npm run build && firebase deploy --only hosting`, with the `/api/**` rewrite to Cloud Run.
- **S17.3** Set `--min-instances 1` on the backend for demo day only (cold starts with Earth Engine init are slow). Set it back to 0 afterwards.
- **S17.4** `scripts/smoke_test.sh`: health → prepare the demo AOI (cached) → default run → advisory. All must pass.
- **S17.5** Security:
  - keys restricted (referrer and API);
  - the bucket is private (signed URLs only);
  - CORS limited to the Firebase domains;
  - no keys in the repo.

---

### S18: Demo preparation, backtest and QA (P0)

- **S18.1** `scripts/preprocess_demo_aoi.py`: prepare Rudraprayag (10×10 km, river) and a Mumbai Kurla/Mithi box (3×3 km, urban) ahead of time, and record their `aoi_id`s in the README.
- **S18.2** Backtest:
  - if GFD has an event over the demo AOI, run a heavy-rain scenario and report the overlap of modelled depth with GFD `flooded` on the Methods page;
  - state that MODIS is 250 m and the event rain is unknown;
  - this is honest evidence, not validation.
- **S18.3** A 3-minute demo script:
  1. India heat map → zoom to Uttarakhand → draw Rudraprayag.
  2. The strip flags the worst day → run "Worst".
  3. Play the hours: water rises, a bridge closes at hour X, routes turn orange.
  4. Capacity gap card → close a shelter → re-run → the gap changes.
  5. Ask in chat: "What if it's 100 mm/h for 3 hours?"
  6. Advisory brief: the three horizons, click the evidence.
  7. Verify a field photo.
  8. Methods + disclaimer.
- **S18.4** QA checklist:
  - all unit tests green;
  - 3 consecutive runs each under 30 s;
  - no console errors;
  - budget under 50%;
  - disclaimer on every results surface.
- **S18.5** Submission, **DECISION**: confirm on the Hack2skill dashboard what is required (repo link, video, deck, write-up), and prepare it by Saturday night.

---

### S19: 3D view (OPT, only if S0–S18 are green by Saturday night)

- **S19.1** **Option B (primary, our own data):**
  - a standalone deck.gl `Deck` with `TerrainLayer` meshed from our Copernicus DEM grid, served as a terrain PNG/heightmap from the backend;
  - `PolygonLayer` extruding Open Buildings footprints by `height_m`, coloured by risk;
  - a translucent water surface per hour: a `SolidPolygonLayer` or `SimpleMeshLayer` of flooded cells at elevation `dem + depth[t]`;
  - synced to the time slider.
  - Never use the Maps Elevation API for terrain (Maps terms §3.2.3(c)(iii)).
- **S19.2** **Option A (backdrop where available):** Maps JavaScript 3D Maps with photorealistic 3D tiles (`Map3DElement` / `gmp-map-3d`). **VERIFY** the current API, overlay support and coverage over the demo AOI. Use it only as a visual backdrop.

---

## 6. Day plan (Wed 14 to Sun 18 Oct)

| Day | Build | End-of-day checkpoint (must be on the deployed URL) |
|---|---|---|
| **Wed 14** | S0, S1, S2, S3-M1 | Draw an AOI → layers prepared → flood depth from a stage slider shown on the Google map |
| **Thu 15** | S3 M2–M4, S4, S5, S6 | Rain scenario → hourly flood + landslide susceptibility + exposure numbers |
| **Fri 16** | S7, S8, S9, S10, S16 Workspace controls | Full what-if loop: close a shelter / block a road → reroute, capacity gap |
| **Sat 17** | S14, S15, S11, S12, S13, remaining S16 pages, S17 | Advisory + chat + history + photo verify, deployed |
| **Sun 18** | S18 (preprocess, backtest, video), submit by **12:00 IST**. S19 only if everything is green. | Submitted |

**If behind schedule only**, cut in this order:

1. S19 (3D)
2. S13 (urban mode)
3. S12 drain photos (keep building photos)
4. S11.4 web incidents (keep datasets)
5. S5 FR (keep the expert ratings)

---

## 7. Unit tests with exact expected values

Each test lives in `backend/tests/` and runs with `pytest`.

| ID | Function | Input | Expected |
|---|---|---|---|
| T1 | `rational_q` | C=0.5, i=50 mm/h, A=50 km² | **347.5 m³/s** |
| T2 | `kirpich_tc_min` | L=10,000 m, S=0.05 | **74.29 min** (±0.01) |
| T3 | `hack_length_km` | A=50 km² | **13.28 km** (±0.01) |
| T4 | `caine_threshold` | D=1, 4, 24 h | **14.82, 8.63, 4.29 mm/h** |
| T5 | `src_point` | HAND=[0.5,1.5,3.0], cell 30×30 m, local slope 0, h=2.0, L=90 m, S=0.01, n=0.035 | V=1800 m³, A=20 m², P=20 m, R=1.0 m, **Q=57.14 m³/s** |
| T6 | `depth_from_stage` | hand=[[0,1],[2,5]], stage=2 | [[2,1],[0,0]] |
| T7 | hourly envelope | rain=[50,0,0] | stage non-decreasing; h[3] == max(h[1..3]) |
| T8 | `ahp_weights` | flood matrix §S4.3 / landslide §S5.4 | CR **0.0128** / **0.0102**; weights as listed (±0.002) |
| T9 | `frequency_ratio` | 100 cells; class A = 20 cells holding 4 of 5 slides | FR_A = **4.0** |
| T10 | transportation solve | D1=100, D2=50; S1 cap 120, S2 cap 100; cost D1S1=5, D1S2=10, D2S1=4, D2S2=6 | total cost **760**; D1→S1 100, D2→S1 20, D2→S2 30 |
| T11 | overflow | as T10 but S2 cap 0 | gap **30** |
| T12 | `tobler_kmh` | tanθ = 0 | **5.04 km/h** |
| T13 | aspect | z = x (rises east) / z = north | **270°** / **180°** |
| T14 | population conservation | any fixture | Σbuildings + Σunattributed = scaled total (±1) |
| T15 | grid round trip | random lon/lat in AOI | error < 30 m |
| T16 | advisory validator | a recommendation citing `S99` | dropped |

---

## 8. Limitations (show on the Methods page; mention in the pitch)

1. **HAND flood mapping** is a steady-state approximation. It doesn't model water velocity, force, debris, backwater, levee failure or recession. Depths are indicative.
2. **The rational method** is designed for small catchments. Applied to the selected area with an envelope (no recession), it gives coarse, conservative estimates.
3. **Resolution:** MERIT Hydro is about 90 m and the DEM is 30 m. Single streets and small drains are not resolved. Copernicus GLO-30 is a surface model, including buildings and trees, which matters most in cities.
4. **Building classes** are proxies from footprint and height until verified by field photos. Open Buildings heights are model estimates.
5. **Population** is a residential estimate (WorldPop). It is blind to day/night and tourist or pilgrim surges.
6. **Landslide** output is susceptibility, not prediction. The rainfall trigger uses Caine's global threshold. The landslide inventory is incomplete.
7. **OSM** roads and shelters can be incomplete in hill towns. Capacities use footprint × floors × Sphere space standards and must be confirmed locally.
8. **No calibration** against gauges. The backtest is a sanity check only.
9. **Licences:** MERIT Hydro and GFD are non-commercial (CC-BY-NC). Commercial use needs other licences or data.

---

## 9. References

- Rennó et al. (2008); Nobre et al. (2011): HAND.
- Zheng, Tarboton, Maidment et al. (2018), *River channel geometry and rating curve estimation using HAND*, JAWRA. TauDEM `CatchHydroGeo`: https://hydrology.usu.edu/taudem/taudem5/help54/CatchHydroGeo.html
- NOAA National Water Model / OWP HAND-FIM (operational use of HAND for flood inundation mapping).
- Kuichling (1889): rational method. Kirpich (1940): time of concentration. Hack (1957): stream length–area. Manning's equation.
- Saaty (1980): AHP. Lee & Pradhan (2007): Frequency Ratio. Caine (1980): rainfall intensity–duration landslide threshold.
- Tobler (1993): hiking function. The Sphere Handbook: minimum covered living space of 3.5 m² per person.
- Barnes, Lehman & Mulla (2014): priority-flood depression filling.
- Yamazaki et al. (2019): MERIT Hydro, https://developers.google.com/earth-engine/datasets/catalog/MERIT_Hydro_v1_0_1
- Tellman et al. (2021): Global Flood Database, https://developers.google.com/earth-engine/datasets/catalog/GLOBAL_FLOOD_DB_MODIS_EVENTS_V1
- Google Open Buildings v3 and 2.5D Temporal: https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings_v3_polygons and https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings-temporal_v1
- WorldPop on EE: https://developers.google.com/earth-engine/datasets/catalog/WorldPop_GP_100m_pop
- NASA Global Landslide Catalog on the EE community catalog: https://gee-community-catalog.org/projects/landslide/
- Maps Platform Terms §3.2.3: https://cloud.google.com/maps-platform/terms
- Weather API REST reference: https://developers.google.com/maps/documentation/weather/reference/rest
- Maps JS deprecations (Drawing Library → Terra Draw): https://developers.google.com/maps/deprecations
- Earth Engine noncommercial tiers: https://developers.google.com/earth-engine/guides/noncommercial_tiers
- ADK tool confirmation and agents: https://adk.dev

---

## 10. Open decisions for the human

| # | Decision | Default if no answer |
|---|---|---|
| D1 | Gemini model names (S0.10) | Current Flash for fast tasks, current Pro for the advisory |
| D2 | Demo AOIs | Rudraprayag 10×10 km; Mumbai Kurla/Mithi 3×3 km |
| D3 | `STREAM_UPA_KM2` | 5 km² |
| D4 | IMD adapter | Skip; Weather API only, IMD cited |
| D5 | Field photos for the demo | Owner's own photos |
| D6 | Live vs preprocessed Gemini photo classification on stage | Decide on demo day |
| D7 | Submission format | Check the Hack2skill dashboard by Fri |
| D8 | Project name | "Pravah" (placeholder) |
