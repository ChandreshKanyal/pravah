# Pravah progress

## State at stop (17 Oct 2026, ~22:00 IST) - read this first

All work is **committed** on `main` (no git remote is configured, so nothing is pushed). Tests 101/101
(`backend/.venv/bin/python -m pytest -q`), `npm run build` clean. Local: backend `uvicorn app.main:app --port 8080`
(restart after backend edits), frontend `vite --port 5173`. Data: Firestore `(default)` and bucket
`pravah-dss-data-project-0fd9c4ae-bf90-452f-a80` (asia-south1). Model: `gemini-3.8-flash` everywhere. Deadline Sun 18 Oct
12:00 IST.

**Deployed tonight (by the agent, at the human's request):**
- Backend revision **00004 (8 CPU / 8 GiB)** is live (23:05). Rudraprayag record rain, 4 h: 176 s on a fresh instance,
  155 s warm (flow model 159 / 142 s); 2 CPU was 263 s, the Mac 57 s. 4x the CPUs gave <2x, so more CPU will not help.
  **Option B done (23:55; deployed 00:05 IST 18 Oct, revision 00006):** `flow_max_cell_hours` 1.2 M -> 1.0 M, so Rudraprayag-sized
  work (1.15 M cell-hours) uses 60 m cells. Validation (all four forced to 60 m, Mac, flow model s / flooded km2 / people):
  Rudraprayag 45->12 s, 1.93->2.00, 1,605->1,608; Amingaon 12->4, 0.14->0.12, 7->7; Kalyan 38->11, 1.61->1.51,
  2,525->1,636; Mumbai 19->7, 3.29->3.24, 17,195->21,172. Cities change too much at 60 m, so they stay at 30 m (0.39-0.69 M).
  The cost is cells x time steps, and Rudraprayag's fast river forces ~1 s steps. Rudraprayag default is now `39d115c1bd7b` (60 m).
- **Flow model compiled at instance start (00:10; deployed in 00006, compiles in 9.1 s on Cloud Run):** `app/main.py` startup thread
  compiles the numba solver and `_breach` on a tiny grid (Mac, empty cache: 5.4 s), so the first Run on a new instance
  no longer pays ~20 s of compiling. The cache is not baked into the image (Cloud Build's CPU may differ from Cloud Run's).
  Why steps are ~1 s: the explicit solver's stability limit (CFL 0.45) set by the fastest water (the river), not detail
  wanted; future options: local-inertial solver, river left to HAND, local time stepping (not for the deadline).
- **State at 02:20 IST 18 Oct (read first tomorrow).** Live: backend revision 00008 + website (landslides removed, India
  only, run jobs, early fixes search; deployed by the human ~02:00). India OSM tiles LIVE: 29,663 tiles, 1.93 GB in
  `gs://pravah-dss-data-project-0fd9c4ae-bf90-452f-a80/osm_tiles/india/` + `_meta.json` (switch-on marker; delete it to
  fall back to Overpass). Built on the Mac in 42 min (11.3 M ways, 1 without locations); a temporary n2-highmem-16 VM
  was tried, lost the race (each shard reads all 28 M ways) and was deleted (~$0.60; no instances or disks left).
  Check vs Overpass (same bundle code): Amingaon and Kalyan identical in drive/walk nodes+edges, bridges, POIs and
  waterways; places 11 vs 12 in Kalyan; tiles 2-4 s vs Overpass 37 s.
  Fixes analysis: 117 s on Kalyan, 89 s of it the Gemini web search (LOW thinking did not help: 115 s vs 62 s);
  the search now starts at prep start (`eb5ed02`): fixes ready 28 s after prep.
  Live new area near Nagpur (23a7ce34d369, before tiles were live): prep 106 s (osm 71 incl. 44 s Overpass, buildings
  28, network 20); run 41 s (flow model 28 s: 13,450 steps of ~1.6 s over 4 h + 2 h tail on a tiny grid, so per-step
  overhead dominates; routing 11 s, unexplained); fixes web search hit Gemini 429 RESOURCE_EXHAUSTED.
  **Next:** (1) retry with backoff on Gemini 429 and image reviews back to 4 at a time (needs deploy); (2) prepare one
  fresh Indian area live and record step timings with tiles; (3) profile routing's 11 s; (4) only if time: move the
  flow model's time loop into numba (re-validate four areas); also refresh the remaining demo fixes lists,
  MIN_INSTANCES=1 for judging (costs money, ask).
- **Scope change (human decision, 01:00 IST 18 Oct; SPEC deviation): floods only, India only.**
  - Landslides removed completely (`635649d`): no landslide index at prep (it was 30-160 s of every prep, and in
    Rudraprayag, the one area where it mattered, it rested on expert ratings with AUC 0.60), no landslide closures,
    evacuation demand, shelter exclusions or building-risk raises, no layers/history markers/brief items/Methods
    sections; `engines/landslide.py`, `engines/fr.py`, `scripts/event_replay.py` deleted. Shelter candidates now need
    slope <= 20 deg (was LSI <= 3). New defaults (flooded areas identical): Rudraprayag `013b5a31b921` 1,608 -> 570
    people to move (gap 1,004 -> 349), Kalyan `53e042d1fe2a` 2,525 (same), Mumbai `8cebf76040ec` 17,195 (gap 53 -> 0),
    Amingaon `baa0cec8d701` 7 -> 6. Tests 91/91 (landslide tests removed).
  - India only (`292811e`): `models/aoi.build_aoi` refuses boxes outside the Geofabrik India boundary
    (`backend/app/data/india.poly`). Japan Trial, Pak, Dera Ghazi Khan and Houston areas archived (reversible).
  - India's OpenStreetMap kept with us: `scripts/build_osm_tiles.py` cuts the Geofabrik India extract (16 Oct, 1.7 GB)
    into 0.1 deg gzipped tiles (roads, waterways, places, POIs) -> `gs://<bucket>/osm_tiles/india/`;
    `services/osm_local.py` serves them to `osm.bundle` in Overpass element form once `_meta.json` (uploaded last)
    exists, else Overpass as before. Multipolygon relations are not in the tiles.

- **Runs never call Overpass (00:45 IST 18 Oct, committed, needs a backend deploy):** a new area's first run (Japan
  Trial, a4e2ac685379) took 416 s, of which the model ~18 s: `places.area_places` fetched place names from Overpass
  inside the run and connections hung. Now: place names come with the roads in the prep bundle (`places.json`); a run
  or brief without the cache gets [] and a background fetch (Overpass failures are no longer cached as "no places");
  `_post` gives up a connection after 15 s (was minutes); OSM buildings (areas outside Open Buildings) go through
  `_post` starting on the second mirror, since prep runs them alongside the roads bundle (Japan buildings 134 s -> 35 s).
  Local check: run without places cache 27 s. Prep of Japan Trial was 181 s (buildings 134, osm 55, lsi 29, network 9);
  a trivial Overpass query waits 29-48 s on the public server. BigQuery's OSM copy is stale (Nov 2022), not usable.
- **Live timings on 00006 (8 CPU), each area's default scenario through the job flow, wall clock:** Rudraprayag 23 s
  (was 150 s; flow 14 s), Amingaon 26 s (flow 21), Mumbai 45 s (flow 31), Kalyan 67 s (flow 59, 9 h storm). People and
  flooded area identical to the defaults (1,608 / 7 / 17,195 / 2,525). Defaults left unchanged.
- **Runs are now jobs (23:20; deployed 23:40, backend revision 00005 + hosting):** a 155 s warm run finished on the server ("200 OK" in the
  log) but the reply never reached the client: a connection silent for minutes was dropped on the way (phone hotspot).
  The website now calls `POST /api/run-jobs` (answers at once with a job id, the run continues in a thread) and polls
  `GET /api/run-jobs/{id}` every 3 s; job state is in Firestore `run_jobs` so any instance can answer. A job still
  "running" after 16 min is reported as lost. `POST /api/runs` is unchanged (scripts, smoke test). Tested locally
  (done after 104 s; unprepared area -> error 409; unknown job -> 404). Live check: Rudraprayag job done in 150 s, run 5b140c8bcd58, 1,605 people (unchanged).
- Website deployed; the production build calls Cloud Run **directly** (`frontend/.env.production`), because Firebase
  Hosting's `/api` rewrite to Cloud Run cuts requests at 60 s and runs now take longer. CORS checked from web.app.
- Deploy fixes: `backend/.gcloudignore` (the upload was 884 MB of local venv), Dockerfile installs `libexpat1` (rasterio
  failed to import on the newer python:3.12-slim) and import-checks compiled libraries at build time.
- `scripts/smoke_test.sh` uses the website URL, so its run step goes through the 60 s rewrite and fails on long runs;
  run it with the Cloud Run URL as BASE, or call the backend directly as above.

Commands: `./scripts/deploy_backend.sh` (add `MIN_INSTANCES=1` for the judging window: no 15 s cold start, small hourly
cost); `cd frontend && npm run build && cd .. && ~/.npm-global/bin/firebase deploy --only hosting --project project-0fd9c4ae-bf90-452f-a80`.

Behaviour the human asked for (keep it):
- **No area mode.** Physics chosen per cell and channel from the data (`engines/profile.py`); AI only for sourced local
  facts (drain capacity lookup), confirmed by a person.
- **The 2D map, people and roads use the flow model** (deepest of river, hollow and flow-model depth each hour; flooding =
  >= 15 cm, or >= 5 cm on slopes < 5 deg). 3D reuses the run's simulation.
- Map opens on **live roads**; scenario layers only after Run. No automatic runs. A run opens at **hour 1**. Map state
  survives trips to 3D/brief/drill (sessionStorage `pravah:ws:{aoiId}`); the shown run is in `?run=`.
- Rain panel: Forecast / Past day / Record / **Custom**; every source has **Average rain over the storm** (starts at the
  actual data; anything else shows "Not the actual ..." and the run label says so), Duration and **Shape** (As forecast /
  As measured, Steady, Early peak, Custom = hand-edited bars). Record = rarity (2/10/25/100-year Gumbel or wettest day).
  Hand-edited runs are named "<source>, edited by hand"; above the world-record envelope the editor warns.
- Fixes: satellite leads only when Gemini confirms and the centre matches; channel leads need water seen from space;
  images open full screen; sources as numbered chips; the Google Search chip stays as Google sends it (required).
- 3D overlays, building colours over time, landslide actions only >= 15 deg, FD2321 evacuation thresholds (standing water
  only off river corridors), Ask Pravah answers only platform/disaster questions, delete runs/areas.

Current default runs: Mumbai d277268c1783 -> bc64e91a5d67 (IMD very heavy, 17,195 to move: likely high, drains are a flat
25 mm/h sink), Amingaon 734b0b1c8987 -> 955fd414a7b3, Rudraprayag 56f044f26351 -> 39d115c1bd7b (60 m flow cells; before: 7ae4e101e63b, made by the live backend,
same result as 935b9f923382), Kalyan d72416dfcfe0 -> ab9f8b47f91d (hand-edited 2150 mm / 9 h). Dera Ghazi Khan
b48178d77d97, Houston de6b9b9e28bf (prepared tonight as a speed test) also exist.

Open items:
- Confirm the 8 CPU revision and its run time (above). Then check the live site in a browser: each demo area, one Run, 3D.
- Rebuild "Fix before the rain" for Mumbai, Amingaon, Rudraprayag with the stricter check (`improvements.build(aoi_id)`;
  only Dera Ghazi Khan was rebuilt).
- `scripts/preprocess_demo_aoi.py all` after the engine changes (heavy on the Mac; overnight).
- Area preparation speed-ups proposed, not done: gzip the graphml files (Houston walk graph 101 MB, re-downloaded by the
  network step: 121 s of its 230 s), a write-through local file cache, vectorised Tobler times (~27 s), lsi in parallel
  with building_proxy. Estimated Houston 9.5 -> 4-5 min.
- Every run still replaces the area default; the drain lookup varies between calls; 3D overlays have no tooltips; South
  Asia OSM extract in Cloud Storage if Overpass gets worse.

## 17 Oct, evening: the flow model drives the 2D map, people and roads
Bug (Kalyan d72416dfcfe0, 2150 mm in 9 h): the 2D map showed 0.026 km2 at every hour while 3D flooded the city. The
HAND + hollow models only hold water in reliable river corridors and closed hollows; Kalyan's channels are tidal or
urban drains (river physics off) and its box has 29 hollow cells, so rain beyond the drains on flat streets was counted
nowhere: 8 people to move vs ~15,000 in water in the flow model.
Now every run runs the 2D shallow-water flow model (`flow.simulate`) and each hour's depth is the deepest of river
(HAND), hollow and flow-model water, worst so far (`flow.hourly_depth`). Flow-model water counts as flooding when >= 15 cm,
or >= 5 cm on slopes < 5 deg (thinner films on slopes are hillside runoff: Rudraprayag 3.06 -> 1.93 km2; flat cities
within 1 %). Water off river corridors uses the still-water evacuation thresholds. The same simulation is uploaded in the
background as the run's 3D water (`flow.store_later`), so 3D does not simulate again. If the flow model fails, the run
falls back to HAND + hollows with a warning. NOTE(spec-drift): SPEC's run is HAND/rational-method screening; the
hydrodynamic model was 3D-only.
Validation (same scenarios as the area defaults; new runs kept; Kalyan's default switched to ab9f8b47f91d, the others NOT yet):

| Area | default run -> new run | flooded km2 (end) | people to move | run time |
|---|---|---|---|---|
| Kalyan, hand-edited 2150 mm / 9 h | 7fd8325be34b -> ab9f8b47f91d | 0.026 -> 1.61 | 8 -> 2,525 | 33 -> 91 s |
| Amingaon, cloudburst | 4812175de1bf -> 955fd414a7b3 | 0.019 -> 0.14 | 7 -> 7 | 7 -> 31 s |
| Rudraprayag, record rain | d143334b8b1b -> 935b9f923382 | 0.23 -> 1.93 | 1,145 -> 1,605 | 15 -> 74 s |
| Mumbai Kurla, IMD very heavy | 46b7490e56ce -> bc64e91a5d67 | 1.55 -> 3.29 | 5,682 -> 17,195 | 18 -> 37 s |

Caveat: the flow model's drains are a uniform sink on built-up cells (25 mm/h default) with no pipe network or Mithi
channel conveyance beyond the 30 m terrain, so Kurla's 17,195 is likely high; it is a planning estimate for review.

## 17 Oct, late evening: cloud review fixes (10 findings, all fixed)
1. Standing-water evacuation thresholds only off river corridors (corridor = reliable reach and river-wet or HAND < 3 m);
   flow-model water beside a fast river keeps the moving-water threshold (~0.28 m, not 0.5 m).
2. `static_depth.npz` (river + hollows alone) saved per run; the 3D "Map (hourly)" comparison and the flow agreement
   check read it (depth.npz now includes the flow model).
3. `models/scenario.apply_rain_change` (and the same rules in Workspace's assistant command): Gemini's plan and the
   assistant's tools reset strength/shape/record rarity on a new source and map an explicit hyetograph to rain_shape.
4. Rain hours: replies for older settings are ignored; "Custom" only offered when the loaded hours match the settings.
5. One flow simulation at a time per instance (`flow._model_lock`), in runs and 3D jobs alike.
6. A source that fell back to default rain hides the strength slider; the run warns "Strength not applied"; the run name
   shows "x k" only when the strength was applied.
7. OSMnx timeouts back to 240 s; the bundle request 300 s; an Overpass "runtime error" (timeout/memory) is not retried
   on every mirror, it falls back to the separate requests.
8. `POST /api/runs?flow=false` skips the in-run flow model (labelled quick preview).
9. A newer run of the same area replaces a 3D upload still waiting (frames are not piled up in memory).
10. Bundle selectors generated from POI_TAGS/WATERWAY_TAGS (waterways now also as relations, like the separate path).
Re-validated: flooded areas unchanged; Rudraprayag people 1,589 -> 1,605 (fix 1). Tests: 101 pass; build clean.

## 17 Oct, ~17:30-18:15: OSM download in one request
The "Analysing the road network" step took 2-6 min per new area. Measured: not the network (200+ Mbps); every
Overpass request waits ~30 s in the public queue (overpass-api.de "at capacity"), mirrors mail.ru (504), kumi (500),
osm.jp, openstreetmap.ru/.fr were down; private.coffee worked at 16:00 (8 s, data ~3 months old) and returned 500 by
18:00; OSMnx itself retries a 429/504 server every 55 s forever; and `_osm` sent 5 requests in a row. Sending them in
parallel made it worse (overpass-api.de refused connections; bridges and places failed).
Now `osm.bundle` sends ONE request (all highways, waterways, places, culverts; 500 m buffer) and cuts the walk and
drive networks locally with OSMnx's own filters and steps (`_create_graph`, truncate, largest component, simplify,
street counts; OSMnx 2.1.1 internals, pinned). Dera Ghazi Khan: 40 s, and identical to the old five requests (drive
10,516 nodes / 27,701 edges, walk 10,651 / 28,960, 36 bridges, 112 places, 12 waterways). If it fails, the old
separate requests run one after another. Mirrors: overpass-api.de, private.coffee, z.overpass-api.de; timeout 120 s.
Houston (de6b9b9e28bf, 10 km, US: OSM buildings fallback) took 868 s in all; its OSM step 406 s, of which ~350 s was
OSMnx building shapes for every road before keeping bridges/places. Fixed (`_subset`: hand OSMnx only the matching
elements): OSM step 114 s incl. two server retries (download 78 s, drive 8 s, walk 26 s, places 1 s), identical output
(drive 50,435 edges, walk 243,306, 1,626 bridges, 12,874 places, 512 waterways). Next biggest: `network` 265 s
(dense city: 75,748 buildings, shelters, route tables). Screen estimate changed to "about 3-5 minutes" (landslide and buildings steps still take 1-4 min). Tests: 99 pass.

## 17 Oct, ~16:30-17:30: rain choices for every source, record rarity, stricter satellite leads
Human review of the Dera Ghazi Khan area (8 points). Done:
- Rain: "Design" renamed **Custom**. Every source now has the same three controls: **Average rain over the storm**
  (starts at the source's own value; any other strength shows "Not the actual forecast/record/IMD category" and the run
  label says so, e.g. "x1.50 the IMD category (not the actual IMD category)"), **Duration**, and **Shape** (As
  forecast/As measured for real rain, Steady, Early peak, Custom = hand-edited bars). New params `rain_shape`,
  `rain_scale` (0.1-5), `return_period_y`; old runs load unchanged (None = the old defaults; "worse than forecast"
  runs show as forecast x multiplier). Cloudburst can now be spread steady; its label then says it is below the IMD
  definition. "Worse than forecast" case removed from the panel (the strength slider replaces it).
- Record: choices "Most years" (2-yr), 1 in 10, 1 in 25, 1 in 100 (estimate) and "Wettest since 2001" with its date,
  from a Gumbel (EV1, method of moments) fit to the area's CHIRPS yearly maxima 2001-2024
  (`earth_engine.chirps_annual_max`, cached `chirps_annual.json`, `GET /api/aoi/{id}/rain-records`).
  NOTE(spec-drift): SPEC S10.5 has only the record maximum. CHIRPS is a 5 km satellite product and reads low against
  gauges (Dera Ghazi Khan record day 47 mm, 17 Aug 2022); the panel says so.
- Map hour band opens at hour 1 when a run loads (was the last hour); back from 3D still restores the hour left.
- Fixes: choked-channel leads need open water seen on the channel from space (JRC occurrence >= 5 % within 150 m):
  all 5 Manka Canal leads in Dera Ghazi Khan had 0 % (tree rows and fields beside a canal too narrow for 10 m), the
  Mithi River hyacinth patches have ~34 %. Each imagery lead gets a 2 km wider view plus the 600 m close-ups; Gemini
  reports what is at the centre now and whether a channel is visible, and only confirmed leads whose centre matches the
  claim are kept (the "Gemini unsure" leads are dropped). NOTE(spec-drift): stricter than S-fixes (unclear was kept).
- Fixes panel: images open in a full-screen viewer (arrows, Esc, "Open full size"); sources are numbered name chips.
  The Google Search suggestion chip stays as Google sends it: Vertex AI grounding terms require it to be shown
  unmodified whenever grounded results are shown (checked 17 Oct).
- Tests: `tests/test_rain_choices.py` (98 pass); `npm run build` clean.
- What-if banner contradicted itself ("50 mm/h ... for 4 h (edited by hand), 2150 mm in 9 h"): hand edits froze the
  source's numbers into the name, and the backend ran every edited hour even past the duration. Now a hand-edited run is
  named "<source>, edited by hand" (totals come from the series), runs exactly `duration_h` hours, old runs' names are
  cleaned on display, and the hour editor warns above the world-record envelope (Jennings 1950, 422 D^0.475 mm).

## 17 Oct, ~15:30-16:30: one model for every area (river / urban mode removed)
Human request: "no mode selection ... uses all the best possible logic ... perhaps use some AI". Physics is chosen per
cell and per channel from the data (`backend/app/engines/profile.py`); AI is used only for local facts with sources.
- **Every area prepares every layer.** Waterlogging hollows and drain candidates (`_urban`) now run for all areas. New
  areas use FABDEM bare-earth terrain (the surface model's building tops gave false slopes and false dams); areas
  prepared as "river" before keep GLO-30 for consistency. There is one size limit, 10 km (was 15 km river / 4 km urban).
  `scripts/backfill_waterlogging.py` added the layers to every existing area (done: Rudraprayag, Amingaon and 2 more).
- **River flooding (HAND) only on reliable channels** (`profile.reliable_reaches`):
  - not tidal (the whole channel within 1.5 m of sea level);
  - not a one-cell stub (Mumbai's Mahim outlet hit the 30 m rating cap and flooded 14% of the box);
  - not an urban drain (under 100 km2 and at least 50% built-up: an engineered nallah; its overflow is the
    waterlogging below);
  - a channel hitting the rating cap in a run is dropped for that run.
- **Waterlogging** fills only hollows whose catchment is at least 30% built-up. **Depth** is the deeper of river and
  waterlogging per cell. **Bridges** close on river stage (reliable channels) or flooded approaches.
- **Evacuation rule unified**: people move where the FD2321 hazard rating reaches "danger for some" (0.75; 0.65 for
  fragile buildings), with Manning speed from the channel slope for river water and v = 0 for standing water. This
  gives 0.5 / 0.3 m for still water and about 0.26-0.3 m for river water (was "any wet building", 5 cm).
  *Spec deviation.*
- **Flow model**: storm-drain capacity applies under built-up cells only (a grid, not one number), ARF applies to every
  area, and the ground keeps its hollows in flat towns (profile urban and flat) and is breached elsewhere.
- **Forecast badges**: the higher of the river badge and the drain-capacity badge.
- **Area profile** (built-up share, slopes, largest reliable river, tidal): one line above the scenario, e.g. "Dense
  city · waterlogging · channels act as storm drains · tides not modelled". It sets 3D exaggeration and ground
  conditioning and never switches a hazard off.
- **Validation** (same storms, old -> new):
  | Area | Flooded | People to move | Note |
  |---|---|---|---|
  | Mumbai, IMD very heavy | 1.55 -> 1.55 km2 | 7,531 -> 5,682 | Landslide closures 857 -> 75 |
  | Amingaon, cloudburst | 0.013 -> 0.019 km2 | 12 -> 7 | |
  | Rudraprayag, record | 0.227 -> 0.232 km2 | 1,159 -> 1,145 | |
  An intermediate version with Mumbai's nallahs treated as rivers gave 67k people to move; that is why urban drains
  are excluded from river physics.
- **Storm-drain capacity with Gemini (AI for local facts only)**:
  - `ScenarioParams.drain_capacity_mm_h` (each run records it); the area default is confirmed via `POST
    /api/aoi/{id}/drain`. `POST /api/aoi/{id}/drain/lookup` runs two Gemini + Google Search lookups and offers a figure
    only with a source (grounding, or a URL that opens and names the city), within 5-150 mm/h, and when the two lookups
    agree within 20%. Nothing is saved until a person confirms.
  - Results: Guwahati gave 7 and 30 mm/h on different calls (Assam SITA report vs news), which is why a person confirms.
    Mumbai's "25 now, 50 planned" (BRIMSTOWAD) came back without a figure in the field, so the default stays. Rudraprayag
    has no figure.
  - UI: "Storm drains" section in the scenario panel (slider for one scenario, "Look up this city", "Use N mm/h").
- Not changed: the flow emulator's drain feature (trained per area); Methods page rewritten ("One model for every
  area"); the prepare dialog has no mode and says what is modelled.
- To do after this: rerun "Fix before the rain" for river areas to add road hollows; re-run
  `scripts/preprocess_demo_aoi.py all` if demo caches must match.

## 17 Oct, ~13:30-15:30: water timeline, building colours, rain panel, state kept, 3D overlays, landslide floor, assistant scope
- **Runaway hour editor (root cause of "water fills the city and never changes")**: the hour-by-hour rain bars rescaled
  to 1.6x the dragged value on every render, so one drag climbed to 450-2,240 mm/h (Mumbai runs 9dcdc0009045,
  8f7faab1186f, 451b75a37db4, labelled "edited by hand"). The city flooded fully in hour 1. Now the scale is frozen while
  dragging, widens only on release, and is capped at 300 mm/h (about the world one-hour record). The backend clamps
  `rain_series_override` to 0-300 (clamped, not rejected, so old runs still load). Opening a saved run with values over
  300 drops its edit and goes back to the source rain.
- **2D flashing**: each hour was a new BitmapLayer (blank while its PNG loaded). Now there is one layer per run, and every
  hour's PNG is preloaded and swapped in (depth and LSI).
- **2D envelope (by design, now labelled)**: the hourly map is the SPEC worst-case envelope. Stage never recedes, and urban
  ponding adds only rain above the 25 mm/h drain capacity, so an early-peak storm floods in its peak hour and then holds.
  The legend reads "Deepest flood so far ... see 3D for water draining away". *Not done:* driving the 2D map from the flow
  model's frames (possible: render `flow/frames.bin` hours to PNG).
- **3D first run**: the hourly model now plays from the start like the flow model (it used to jump to the last hour). It
  switches to the flow model when that finishes, unless the person chose a model, and no longer refetches on every
  flow-status poll.
- **3D buildings by water over time**: each building takes the deepest water in the grid cells under its footprint, padded
  by half a cell, for the frame nearest the current time. Grey under 15 cm, yellow from 15 cm, orange from 50 cm, red
  from 1 m. Recoloured only when a building changes class. The brief's static risk colours remain when no water frames
  are loaded.
- **Rain panel redesign**: one switch with four sources (Forecast / Past day / Record / Design). Each source shows its
  choices in the same "label over chips" layout:
  - Forecast: Day, plus Case (as forecast / worse than forecast with a multiplier).
  - Past day: recent days and the wettest days.
  - Design: Strength (IMD heavy, very heavy, extreme, cloudburst, your own).
  Then come Duration, Shape and the hourly card, which shows its total and peak. "Intensity" is now "Average rain over the
  storm", because early peak concentrates it (72 mm/h for 7 h means a 264 mm/h peak hour). The IMD chips no longer silently
  switch the source. A new River section holds river level and upstream flow (moved out of Advanced).
- **Map state survives 3D / brief / drill**: settings, layers, tab, hour, map type, the shown run and the camera are saved
  per area in sessionStorage (`pravah:ws:{aoiId}`) and restored, without re-fitting the view. The shown run is written to
  `?run=`, so 3D opens the same run.
- **Assistant scope**: Ask Pravah now answers only about Pravah itself, floods, landslides, rain and weather, and disaster
  response. Anything else (coding, health, jokes, "ignore your instructions") gets a one-sentence redirect, and no tools
  are called. Tested: a Rust for-loop question, hay fever, and a jailbreak-style request are all refused; Guwahati flood
  areas and "which bridge closes first" are still answered. Replies no longer show raw `###` or backticks.
- **Roads closing with no water (landslide false positives)**: in Amingaon (Guwahati, run 93ce3ee37bf7, cloudburst),
  459 of 479 closed road pieces were "landslide". The LSI classes are relative to the training region, and the only slope
  rule was "under 5 deg is flat", so 19% of cells reached class 5 under the cloudburst (median slope 13 deg, some 6 deg):
  embankments and gentle rises. `landslide.actionable` now also caps cells under 15 deg at class 3 (no closures,
  evacuations or shelter exclusions); the map still shows susceptibility.
  - Amingaon, same settings (rerun c04836132325): landslide closures 459 -> 55, people to move 122 -> 12, no shelter
    place 57 -> 0.
  - Rudraprayag, record rain (e6c49d1a3cfc vs 630921409644): people to move 1,281 -> 1,159.
  - *Spec deviation*: the 15 deg action floor is new (literature lower bound for rain-triggered shallow landslides).
- **3D overlays**:
  - Water is clipped to the simulated area, as on the 2D map. The hourly HAND frames had drawn lakes on the far bank of
    the Brahmaputra, outside the box.
  - Dry buildings are grey (196,199,204) instead of near-white.
  - The model switch shows the model actually drawn, with the flow model's progress, and cannot pick the flow model
    before it is ready.
- Note: these verification runs became their areas' default runs: Amingaon c04836132325, Rudraprayag e6c49d1a3cfc
  (no flow model). A backend restart leaves a queued flow model "stale" for 5 min; the 3D page then restarts it.
- **3D scenario layers (as in 2D)**: new endpoint `GET /api/runs/{id}/3d/overlays.json` returns the run's roads (closure
  hour, reason, blocked pieces), exit routes, shelters in use and closing bridges, converted to the 3D frame (UTM metres
  from the grid centre, gzip, cached per run; Amingaon 87 KB). `three/overlays.ts` drapes them on the ground and follows
  the model hour:
  - Roads are light grey, and turn orange (closes later) or red (closed now) on the blocked pieces only.
  - Exit routes are teal with a dark casing, width by people; once a road on a route closes it turns pale and dashed.
  - Shelter zones are a blue ring (80 m) with a pin and a label ("S9 · 252 people").
  - Closing bridges use the 2D marker icons.
  Chips toggle each layer, and the legend lists them. The lines are opaque, and the casing and base roads write no depth
  (transparent wide lines and equal-depth layers looked beaded).
- Verification run fdbf999057a3 (Mumbai, IMD very heavy, 7 h, early peak; peak 71 mm/h) is now Mumbai's default run,
  replacing the broken 2,237 mm/h one.

## 17 Oct, afternoon

- Fixed: Firestore now rejects arrays inside arrays (`overlay_corners`): `services/firestore.py` wraps inner arrays as
  {"_a": [...]} on write and unwraps on read (new runs were failing to save). Run list (`/api/aoi/{id}/runs`) uses a field
  projection plus an in-memory per-run summary (13 s -> 0.1 s); Projects counts use the projection too.
- Preparation: "Fix before the rain" runs in a background thread after the area is ready (`improvements.start`, chip shows
  the step); channel rasterising in one pass (was minutes in a large city); a preparation interrupted by a restart resumes
  when the area is chosen again (`prepare_area.ACTIVE`); OSM building footprints when Open Buildings has no coverage
  (`osm.buildings`), heights from `height` / `building:levels`.
- 3D: buildings were not drawn after a comment swallowed the `.then` chain of the buildings fetch (fixed); the shaded
  base texture no longer overwrites Sentinel-2 imagery when it loads later; empty building lists are not cached.
- Street View: Google-only outdoor panoramas within 100 m / 300 m / 1 km (user photo spheres rendered black), Back to map
  button, Esc, overlays hidden while open.
- Snackbar: the same message replaces itself instead of stacking.

## 17 Oct, late morning: map declutter and "Fix before the rain"

- **Map declutter** (human: "too cluttered"): rasters, roads, closing bridges and hospitals cut at the drawn box (people and
  flooded area are only counted inside it; the 3 km buffer is hydrology only); default layers are flood, road status,
  routes, shelters in use, closing bridges; marker ids only at zoom >= 15; smaller shelter markers. Google POI density
  can only be lowered in the Cloud Console map style (Map ID), not in code.
- **Fix before the rain** (human asked for Gemini to look at Street View/satellite near drains, garbage, parked cars and flag
  spots with proof). Built differently, on purpose (decision): Google satellite/Street View may not be sent to AI (Maps
  terms), and 10 m open imagery cannot see a blocked drain or rubbish, so a Gemini "finding" there would be invented.
  Three evidence kinds, kept apart in the UI: **web** (Gemini + Google Search; a link is kept only if its site was a
  grounding source or the page opens and names the place; Google geocoding, vague results dropped; compared with HAND /
  road hollows), **imagery** (Sentinel-2 NDVI on mapped rivers/canals, culverted stretches excluded; Dynamic World built-up
  or bare-ground change since 2016-17 on former wetland or the floodway; Gemini reviews before/after or true/false-colour
  clips and leads it says the images contradict are dropped), **model** (culverts and drain crossings by catchment and
  people on low ground, bridge openings capped at 3; urban road hollows 2-300 cells; graph-bridge roads that are the only
  drivable way out, on low ground or over a stream). People open Google imagery/Street View themselves; "Check in the
  field" opens Field check with the place preset. Code: `engines/improvements.py`, `pipeline/improvements.py` (steps
  `clogged`, `congested`, `improvements`, run in the background once the area is ready), `api/improvements.py`,
  `src/components/ImprovementsPanel.tsx`; Methods section "Fix before the rain". Links: `?fixes=1`, `?fix=I3`.
  Built for both demo areas (Mumbai 20 items: 2 reported, 8 culverts/bridges, 6 single exits, 2 low spots, 2 new
  construction; Rudraprayag 15). About 1.5 min per area. Tests 92/92, tsc clean.
- **Ask Pravah everywhere** (human request): one Gemini assistant on every page (`agents/assistant.py`, `POST /api/assistant`,
  `src/components/Assistant.tsx`) replaces the map-only chat. General facts via Gemini + Google Search (sources shown);
  `find_place` (geocoding), `list_my_areas`, the read-only analysis tools when an area is open; anything that moves,
  prepares, runs or switches layers is a *proposed action* the user confirms (run settings validated against
  ScenarioParams). Map commands go through a `pravah:command` event (pending in sessionStorage until the map loads).
- Afternoon fixes: live roads (Google traffic) until a scenario is run in the visit; road closures drawn only on the
  hazard stretches ("no through road" for the rest); Firestore nested-array encoding (new runs were failing to save);
  run list via field projection + summary cache (13 s -> 0.1 s); "Fix before the rain" runs after the area opens;
  interrupted preparations resume; OSM building fallback outside Open Buildings coverage; delete runs and areas.

- Loading screen now speaks in stages (terrain, weather and history, roads, population, infrastructure, risk, clogged
  drains, congested roads, analytics) with the active one spinning.

## Overnight pass (16-17 Oct, human asleep: "do whatever you want")

Human asks, in order: merge Decision/Analyst into one view; rain options must change the simulation accurately; remove the
India past-flood/landslide overlays (mostly rivers); bridges closed only when under construction or overtopped; make real
use of AI/GenAI for a production-grade simulator and preparedness tool; self-explanatory journey; a Projects tab to keep
areas and runs as experiments; then audit the engine and fix flaws. All of it is **uncommitted** (see "State at stop").

**Done and verified (tests 86/86, `npm run build` passes, screenshots checked):**
- One view (no mode switch); rain presets server-side (`rain_preset`), IMD-consistent "Early peak" design storm, cloudburst
  fixed (100 mm in the peak hour), live preview of the exact hourly rain, "settings changed" notice; India map overlays gone.
- **Bridges** (`engines/bridges.py`): real OSM spans (the routing graph merges spans into km-long edges), deck height = HAND
  at the abutments (3 m minimum, flagged), close only when the reach stage reaches the deck (optional margin,
  `bridge_margin_m`) or from hour 1 when OSM says construction/closed/disused; flyovers never close on stage. Backfilled for
  all prepared areas (`scripts/build_bridges.py`); new areas get it in the network step.
- **Landslide road closures** use the landslide index with the distance-to-road factor neutral (`lsi_static_noroad`):
  road cells were 6.5x over-represented in class 5. Rudraprayag record rain: roads closed 138 -> 36, bridges closing
  14 -> 2, people to move 2,295 -> 1,281, gap 1,367 -> 617 (the LSI was also recomputed with current training code).
- **FSI** ignores satellite flood pixels > 20 m above drainage or on slopes > 10 deg. **Dry forecast** windows no longer
  start in hours already past.
- **Projects page** (`/projects`): areas, every saved run with title, notes, star, compare (up to 3), default run (what
  Brief/Map/3D open), archive, copy link; `?run=` opens any run on Map, 3D and Drill, and the area nav keeps it.
  Optional run name before running.
- **AI emulator** (`engines/emulator.py`, `pipeline/emulator.py`): ~100 shallow-water runs per area (64-storm Sobol
  design + 36-run sweep), POD + thin-plate RBF on physically meaningful features (rain above drain capacity, its peak,
  total, duration, river level), leave-one-out validated. Mumbai: median CSI 0.97, p10 0.87, depth MAE 1.5 cm; answers
  in ~2 ms. "What-if" tab: live sliders, overlay, people in knee-deep water, IMD category, "set up as full scenario".
- **Rain triggers** per OSM settlement (mm in 1/3/6 h, IMD category) from the physics sweep itself (not the emulator,
  which was inconsistent at 1 h).
- **Gemini tabletop drill** (`agents/drill.py`, `/area/:id/drill`): deterministic model timeline -> 7-9 grounded injects
  (ids and numbers checked, 2 labelled fictional), each decision scored 0-3, after-action report; rules fallback.
- **CAP 1.2 public alert drafts** (`agents/alerts.py`, Brief -> "Public alert"): EN + HI text checked against facts,
  flooded-area polygons, CAP levels, status always Draft, XML for SACHET.
- **2D-model cross-check** in Results (HAND map vs shallow-water model: area, people, agreement) and people counts in the
  flow summary. Ask Pravah has two new tools: `instant_what_if`, `rain_triggers`. Brief rules/prompt treat
  construction bridges as "confirm with PWD", not "close".
- "Next steps" row in Results (brief, 3D, drill, Projects). Demo areas refreshed (`preprocess_demo_aoi.py all --force
  lsi,fsi`): Rudraprayag default run `f253c9ee67ec` (Gemini brief), Mumbai `7005b50db709` (10,829 to move, gap 498; 14
  bridges closing = OSM construction, urban mode has no river stage). Old default runs remain in Projects.

**17 Oct morning (human back):**
- Hour-by-hour rain editor (`components/RainHours.tsx`, `POST /api/aoi/{id}/rain-hours`): the exact mm per hour the
  model will use, filled automatically from the source (forecast day, worst, record, IMD preset, custom, or the new
  **Past** source: a past day's observed rain from NASA IMERG, `rain_source=observed` + `observed_date`, with chips for
  the last 10 days and the 3 wettest of 90). Dragging an hour makes it `rain_series_override` (label "... (edited by
  hand)", clock kept via `override_start_local`); changing any rain setting refills it; Reset returns to the source.
- Engine flaw fixed: the 2D model stopped when the rain stopped, so water arriving later from uphill never counted
  (short storms looked safer than long ones in the triggers). It now runs `TAIL_H = 2` h after the rain (3D timeline
  extends with 0 mm hours; emulator training uses it too). **The emulators, triggers and demo flows computed overnight
  predate this and must be recomputed** (heavy on this 8 GB Mac: run when the laptop is free).

**Open / next (overnight, as of 17 Oct ~07:40 IST):**
- This Mac (M1, 8 GB) swapped hard under several numba jobs plus the desktop apps (115 MB free, 3.4 GB compressed);
  model runs slowed from ~12 s to ~3 min. Firestore writes then timed out and killed two jobs: emulator and flow
  status writes are now best effort (final state retries). Training is cheaper now: big grids (> 200k cells) train on
  60 m cells with 32 Sobol storms + 10 sweep sizes; `train(aoi, sweep_only=True)` keeps the stored emulator and
  reruns only the trigger sweep.
- Running in the background: Mumbai trigger sweep (keeps its validated 66-run emulator, median CSI 0.97), then
  Rudraprayag full training at 60 m. Check `GET /api/aoi/{id}/emulator` -> "ready" and `/triggers`. If it did not
  finish: `cd backend && .venv/bin/python -c "from app.pipeline import emulator; emulator.train('56f044f26351')"`.
- Bug found and fixed after the demo refresh: OSM "under construction" bridges (closed from hour 1) set the evacuation
  deadline to "before the rain starts" and counted as storm closures. Now only bridges the river overtops drive the
  deadline, K4 and the "Bridges closed" label (test added). **The Mumbai default run `7005b50db709` was made before
  this fix: re-run it** (`backend/.venv/bin/python scripts/preprocess_demo_aoi.py mumbai`, then POST its flow).
- Both demo briefs are Gemini now (Mumbai v2). 3D flow ready for both new default runs (Rudraprayag 2D model wets
  3.15 km2 vs HAND 0.23 km2, CSI 0.04: shown as "models disagree" in Results; Mumbai CSI 0.36).
- Urban mode: Mithi river bridges never overtop (no river stage in urban mode); stated limitation.
- Nothing committed. Suggested commits: (1) engine fixes (bridges, road-neutral LSI, FSI mask, forecast window, presets);
  (2) flow model + 3D page; (3) AI: emulator, triggers, drill, alerts, chat tools; (4) Projects + journey; (5) theme +
  legends (the stopped sub-agent's work: reviewed overnight; the key lists only symbols drawn at the selected hour from the
  same definitions as the map, red = closed throughout, so "Road closed" appears whenever closed roads are drawn); (6) docs. Never commit `backend/cache/*.json`; no AI co-author.

## Previous hand-off (2026-10-16 20:30 IST, after the policy review and the 3D water-flow pass)

**Where we are:** S0-S19 plus a policy-maker review pass, all committed **locally**. Backend tests 81/81
(`cd backend && .venv/bin/pytest -q`); frontend `npm run build` passes; local smoke test passes
(`scripts/smoke_test.sh http://localhost:8080`). UI checked in a real Chrome window (Brief, Map, Compare, Methods track
record, Field check at phone width). **Deployed:** still only S0; the human redeploys.
**Local preview:** backend `cd backend && .venv/bin/uvicorn app.main:app --port 8080`, frontend `cd frontend && npx vite`
-> http://localhost:5173. One view for everyone (the Decision/Analyst switch was merged away on 16 Oct): every control and layer is shown.

**What changed in the policy review (16 Oct):**
- Brief rebuilt for a District Magistrate: deterministic bottom line (who moves, from where, by when, shelter gap), rounded
  figures with a sensitivity range (depth +-30 %, population +-20 %), "who must move" breakdown, OSM place names and landmarks
  instead of ids, one responsible department and a deadline per action, Sphere supplies, official IMD/CWC panel (typed by
  staff) with IMD, CWC and Google Flood Hub links, Draft -> Reviewed -> Approved with immutable versions and an audit trail,
  Hindi (numbers checked), WhatsApp / 2G plain text.
- Map: clock times for forecast scenarios and an evacuation-window marker, IMD rain presets, pilgrims/tourists input,
  gauge-style river input, searchable shelters, only used shelters drawn, one meaning per colour (red = closed), dashed
  white area boundary, scenario comparison tab, technical layers and 3D (now in the single merged view).
- Field check works offline on phones (IndexedDB queue, device location). Sign-in and roles coded, **off by default**
  (enable: docs/CONFIG.md). Old areas can be archived from Explore.
- Evidence: `scripts/event_replay.py` replays IMERG rain of recorded events; results on Methods -> Track record.
  **Finding:** the Himalayan landslide trigger was NOT reached for any of 3 recorded Rudraprayag events (0.36-0.95 of the
  threshold) -> stated in Methods, limitations and every brief where the trigger is not reached. Mumbai: reached for both.

**What changed in the 3D water-flow pass (16 Oct evening):**
- New second flood model for the 3D view: `engines/swe.py`, the 2D shallow-water equations (finite volume, HLL, Chen &
  Noelle 2017 hydrostatic reconstruction, implicit Manning, CFL 0.45, outflow-only edges), numba-compiled. It runs
  automatically in the background after every scenario (`pipeline/flow.py`, Firestore `flows/{run}`), about 1 min for
  Mumbai and 2-3 min for Rudraprayag at 30 m on 2 vCPU (longer storms over big areas switch to 60 m cells). Frames every
  5 min (depth + velocity) go to GCS `runs/{id}/flow/frames.bin` (gzip, 2.5-5 MB).
- Ground: FABDEM bare earth for all areas (`services/terrain.py`); hilly areas are breached 4-connected (Lindsay 2016) so
  streams pass the false dams of narrow gorges. Before: canopy pits of 15-28 m filled with water.
- Checks (`tests/test_swe.py`, 6): lake at rest exact, Manning steady depth on 5 % and 60 % slopes, mass error ~1e-15,
  no inflow through the edge, inflow volume, breaching, frame coding. Backend tests 81/81.
- 3D page rebuilt in three.js (`frontend/src/three/`): terrain from the same ground, Sentinel-2 true colour (Earth Engine,
  cached per area), water as an animated surface (flow-advected ripples, sky reflection, foam on fast water, smooth
  shorelines), white flow lines, "Danger to people" colouring (FD2321 hazard rating), model-cell boxes, click a
  spot for its depth/speed now, arrival and peak time and a depth-over-time chart, continuous storm timeline with speed.
- Demo runs have flow results: Rudraprayag `cd03a7237c8c` (max 5.7 m, 6.1 m/s, water >= 5 cm on 3.1 km², 53 % of the HAND
  flood area also wet); Mumbai `b72eb7c305fb` (max 3.3 m, 4.2 km², all of the HAND ponding area also wet).
- The brief and 2D map still use HAND (and the SPEC §2.4 disclaimer names HAND); the flow model is shown next to it.

**State at stop (16 Oct ~21:00 IST, human paused work to review): NOTHING from the 3D water pass is committed.**
- Done and checked in Chrome (uncommitted): flow model + API + 3D page (above), Methods "Water flow (3D)" section,
  README API rows, smoke test checks that the flow job starts, numba in `backend/requirements.txt` (+ `NUMBA_CACHE_DIR`
  in the Dockerfile), `@deck.gl/mesh-layers` removed (3D is three.js). Backend tests 81/81; `npx tsc --noEmit` clean.
  API path verified: POST `/api/runs/90bbc88655b8/flow` -> queued -> running -> ready in 68 s (30 m, Mac).
- A sub-agent ("day/night toggle + legend audit", human request) was **stopped mid-way**, its work is unreviewed:
  restored theme toggle (`frontend/src/theme.ts`, App.tsx top bar, MapCanvas colour scheme, index.html), 3D pill in the
  Decision nav, and partial legend/colour/road-status edits in `MapLegend.tsx`, `layers/factories.ts`, `LayerPanel.tsx`,
  `Results.tsx`, `TimeSlider.tsx`, `Workspace.tsx`, `styles.css`. It had checked tooltips vs legend (Decision view) and was
  about to check the technical layers (the views are now merged). Next: review that diff, finish the legend audit (one colour = one meaning, swatches match
  rendering, "Closed" entry whenever roads are drawn closed, light + dark, both demo areas, hour 1 and last hour).
- Then: `cd frontend && npm run build`, screenshots, commit in logical pieces (backend flow model; 3D page; theme +
  legends), never with an AI co-author line.
- Uncommitted flow fixes not yet in the running backend: stale-job rule (5 min without progress) and 10-minute frames
  for storms > 6 h; restart uvicorn to pick them up. `backend/cache/*.json` files are local caches (do not commit).

**Human to-do (in order):**
1. Deploy (agent deploys are blocked):
   `./scripts/deploy_backend.sh` then `cd frontend && npm run build && cd .. && ~/.npm-global/bin/firebase deploy --only hosting --project project-0fd9c4ae-bf90-452f-a80`
2. Smoke test the live URL: `./scripts/smoke_test.sh`.
3. Decide on sign-in for the demo (docs/CONFIG.md steps; leaving it off lets judges try everything, approvals then record
   typed names as unverified).
4. Demo day only: `MIN_INSTANCES=1 ./scripts/deploy_backend.sh`; set back to 0 afterwards.
5. Click through: Explore -> Rudraprayag -> Brief (Hindi, Share, Approve) -> Map (hours, compare) -> Methods
   track record; scenario presets, 3D, Ask Pravah.
6. S18.5: confirm submission requirements on the Hack2skill dashboard (repo, video, deck, write-up).
7. Optional: confirm NASA GLC and GRIP4 licence terms; Weather API caching period.

**Demo areas** (cached; latest run + Gemini brief ready): Rudraprayag `56f044f26351` (record rain, run `cd03a7237c8c`:
about 2,300 to move, range 1,850-2,750, gap about 1,350, move before hour 4) and Mumbai Kurla-Mithi `d277268c1783`
(60 mm/h early peak 3 h, run `b72eb7c305fb`: about 10,900 to move, range 3,450-22,600, gap about 840, named
neighbourhoods). Re-run `scripts/preprocess_demo_aoi.py all` after engine changes; `scripts/rerender_pngs.py` after
render changes; `scripts/event_replay.py` to refresh the track record (it changes each area's latest run, so run a demo
scenario afterwards).

**Key config knobs** (`backend/app/config.py`): Gemini model/thinking; `lsi_threshold`; `lsi_modulation`; `lsi_close_share`;
`apply_arf`; `urban_drain_capacity_mm_h`; `urban_evac_depth_m` / `_fragile_m`; `auth_required`, `admin_emails`, `default_role`.

**Known limits:** HAND/rational screening, no gauges; landslide trigger misses satellite-rain cloudbursts (see track
record); urban = ponding only (no Mithi overflow or tides); OSM gaps in hill towns; clock times only for forecast
scenarios; Gemini HIGH thinking takes about 1 min per brief (background job); IMD/CWC values are typed in, not fetched.

## Stage log

| Stage | Status | Date-time (IST) | What works | Deviations from spec | Open questions | What the human must do |
|---|---|---|---|---|---|---|
| S0.9 scaffold | done | 2026-10-15 | Repo layout per SPEC §3.5, venv (py3.12), deps installed and pinned in `backend/requirements.txt`, config + CORS app stub | Frontend `src/` dirs only; Vite app comes in S0.13 | | |
| S0.10 list models | done | 2026-10-15 | `scripts/list_models.py` runs on Vertex (global), lists 30 Gemini models | One model (`gemini-3.8-flash`) with thinking levels, per human (see Decisions) | | |
| S0.11 health | done | 2026-10-15 | `GET /api/health` returns ok with ee, vertex, firestore all true locally; unit test passes | | | |
| S0.12 Cloud Run | done | 2026-10-15 | Deployed `pravah-backend` (asia-south1); `https://pravah-backend-265255051442.asia-south1.run.app/api/health` returns ok, ee, vertex, firestore all true | Needed IAM roles on default compute SA for Cloud Build (human granted); service is public | | |
| S0.13 Firebase | done | 2026-10-15 23:30 | `https://project-0fd9c4ae-bf90-452f-a80.web.app` serves Hello Pravah; `/api/health` via rewrite returns ok, ee, vertex, firestore all true | Deploy run by human (agent deploys blocked by permission classifier) | | Done: browser key referrers now include web.app and firebaseapp.com |
| S1 AOI + base layers | done (local), not deployed | 2026-10-16 00:00 | `POST /api/aoi`, `GET /api/aoi/{id}/status`, `/static-layers`, `/api/layers/{id}/{name}.png`. Rudraprayag 10 km: all 18 S1 layer keys on one 543x528 grid (6 groups in GCS), 9,946 buildings, OSM walk/drive graphs, POIs, waterways. Fresh AOI prepares in 56.8 s (EE groups 4-22 s, buildings 41 s, OSM 48 s). pop30 sum = EE total (59,546; 0.001%). DEM 593-2,872 m. HAND along OSM rivers: median 6.1 m vs 190 m grid-wide. Unit tests 9/9 (T13, T15). | (1) Population key is `pop30` (S1.6/S6), not §4.2 `pop100`. (2) Overlay PNGs served via `/api/layers/...` proxy instead of V4 signed URLs (signing needs extra IAM; works locally and on Cloud Run). (3) `d8` on the 30 m grid is nearest-resampled, display only; S2 uses native MERIT. (4) Buildings fetched for the AOI bbox, not the 3 km buffer. (5) Overpass primary = overpass.private.coffee (overpass-api.de was at capacity, 290 s), fallback overpass-api.de. (6) S2/S4/S5/S6/S7/S9 hooks in prepare_area come with those stages; keys reach_id, drain_cell, fsi, lsi_static not yet produced. (7) DEM max 2,872 m exceeds the spec's rough 2,500 m: ridges in the 3 km buffer. | Public Overpass mirrors can be flaky; S18 preprocesses demo AOIs so the live demo reads from cache. | Redeploy backend (`./scripts/deploy_backend.sh`) - I am blocked from deploying. Visual HAND-vs-satellite check once the map exists (S16). |
| S2 hydrology prep | done (local), not deployed | 2026-10-16 00:20 | Native MERIT 3" grid (202x180), D8 downstream, local accumulation (Kahn), drain cells, 70 reaches (max A_up 10,485 km2, Alaknanda), catchment per cell, SRC tables (n=0.04) all monotone with Q(0)=0 (e.g. main reach: 1,000 m3/s -> 3.6 m), 15 hotspots, `reach_id`/`drain_cell` mapped to the 30 m grid (89% coverage). Streams PNG: 98% of OSM river vertices within 120 m of a stream cell. Runs in 4 s. Tests 15/15 incl. T5. | (1) Reach heads = stream cells with n_up != 1; the spec's extra rule (downstream is a confluence) would create 1-cell reaches, so a reach instead ends at the cell before a confluence. (2) Outputs: `hydro_native.npz`, `hydro_grid.json`, `reaches.json`, `src_n0.040.json` (cache keyed by n), `hotspots.json`, `png/streams.png`; `/static-layers` now returns streams + hotspots. | Top hotspots cluster at the main confluence (several MERIT cells); may dedupe within ~300 m for display. MERIT `hnd` drainage differs slightly from our 5 km2 threshold (note for Methods). | Visual stream-vs-satellite check at S16. |
| S3 rain -> flood | done M1-M3 (local), not deployed | 2026-10-16 00:45 | `POST /api/runs` (ScenarioParams -> RunResult), `GET /api/runs/{id}`, per-hour depth PNGs at `/api/runs/{id}/layers/depth_hN.png`, `depth.npz` (float16) in GCS, temporary `GET /api/aoi/{id}/flood.png?stage=` (M1). C_reach = upstream-mean C via weighted Kahn accumulation; Kirpich+Hack tc; envelope per reach; depth via reach_id lookup; hotspots get depth/stage at worst hour. Rudraprayag 4 h: 20 mm/h -> 0.38 km2, max stage 1.8 m; 100 mm/h -> 0.79 km2, 4.6 m. Warm run 0.27 s (cold 4.4 s incl. loading area). Tests 24/24 incl. T1-T4, T6, T7. | (1) Only `manual` rain until S10; other sources fall back to manual with a warning. (2) RunResult adds `overlay_corners` (4 corners for deck.gl) and `timings_s`. (3) Hotspots in permanent water report `in_river_channel` instead of depth 0. (4) S3.5 (M2 single reach) skipped: went straight to per-reach M3. | Flood extents look narrow in this gorge (HAND rises fast); `river_offset_m` lets users add pre-existing high water. | |
| S4 FSI | done (local), not deployed | 2026-10-16 00:55 | `engines/ahp.py` (eigenvector AHP, CR check), `engines/fsi.py` (7 factor scores, weighted sum, 5 classes); matrix in config (`fsi_ahp_matrix`). Rudraprayag: CR 0.0128, weights [0.236, 0.165, 0.148, 0.148, 0.135, 0.092, 0.077]; mean FSI 0.50 on HAND<5 m vs 0.08 on HAND>100 m; classes 1-5: 89.6/7.7/2.0/0.6/0.1%. `png/fsi.png`, listed by `/static-layers`; weights/CR stored in `aois/{id}.meta.fsi`. Tests 27/27 incl. T8 (flood). | `hist` p99 is taken over the AOI grid (the spec's "training box"). | Methods page (S16) will read weights/CR from `meta.fsi`. | |
| S5 landslide susceptibility | done (local), not deployed | 2026-10-16 01:30 | `engines/fr.py`, `engines/landslide.py`: 8 factor classes, FR or expert ratings, AHP weights (CR 0.0102), training region = AOI + 50 km on a 90 m grid (1221x1225), min-max + quantile classes from training, slope < 5 deg -> class 1; runs add `lsi_dyn_class` per hour (Caine), `lsi.npz`, `lsi_hN.png`, `lsi_png_url` = worst hour. Rudraprayag: class 1->5 mean slope 24 -> 37 deg, share within 150 m of a road 9% -> 76%; 10 mm/h x 1 h lowers classes, 60 mm/h x 4 h raises them. Static LSI adds ~61 s to prepare (training fetch). Tests 33/33 incl. T8 (landslide), T9. | (1) **Landslide records limited to location accuracy <= 1 km** (config `landslide_max_accuracy_km`), not the spec's 10 km: with 5-10 km points FR rated the flattest slope class highest. Rudraprayag then has 9 records -> expert ratings + warning. Set 10 to follow the spec. (2) No OSM roads for the 100 km training box: road factor uses expert ratings, and its mean rating in the training distribution. (3) Curvature bins applied at 90 m (training) and 30 m (AOI) without rescaling. (4) `RunResult.lsi_png_url` points to the worst hour; per-hour PNGs follow the `lsi_hN` pattern. | GLC licence not stated in the EE asset metadata (NASA GLC via sat-io community catalog); confirm before submission. Could run the LSI training fetch in parallel with S1 fetches to cut prepare time. | Decide on the 1 km vs 10 km landslide accuracy rule (default 1 km). |
| S6 buildings, population, exposure | done (local), not deployed | 2026-10-16 02:05 | `engines/buildings.py` (proxy classes, KD-tree cluster rule, field-photo override hook), `engines/population.py`, `engines/exposure.py`; prepare adds `buildings_proxy.parquet` + `pop_unattributed`; runs fill `exposure`, `triage`, clusters (300 m), `verification.json`; `GET /api/aoi/{id}/verification-queue` (latest run). Rudraprayag: 9,946 buildings (3,370 makeshift/hut, 2,602 kaccha/low-rise, 2,028 informal cluster, 1,303 pukka low-rise, 616 multi-storey, 27 new unplanned); population conserved (5,311 in buildings + 54,235 grid = 59,546). Flood-exposed at hour 4: 136 / 230 / 292 people for 20 / 60 / 100 mm/h. Run ~1 s warm. Tests 38/38 incl. T14 and hand-computed risk. | (1) Population shared per **90 m block** (3x3 cells, WorldPop scale), not per 30 m cell: per-cell left 97% unattributed. (2) Cluster count includes the building itself. (3) Unattributed grid people in clusters use F = 0.8. (4) Verification queue comes from the AOI's latest run (`aois/{id}.latest_run_id`). | **Landslide exposure saturates**: Caine's global threshold (8.6 mm/h at 4 h) puts g at its 1.5 cap for any rain >= ~13 mm/h, so ~32k people sit in LSI class >= 4 and 4,372 buildings are raised to "high" in every scenario. A regional threshold (e.g. Uttarakhand) would discriminate better. Open Buildings coverage is thin here (only 9% of residents placed in buildings; warning shown). | Decide whether to swap Caine for a regional rainfall threshold (config). |
| S7 roads, shelters, staging | done (local), not deployed | 2026-10-16 03:00 | `engines/roads.py` (30 m edge sampling, Tobler walk times, OSMnx drive times, bridges, LSI/steep-slope attributes, narrowness), `engines/shelters.py`; prepare writes `edges_/nodes_{walk,drive}.parquet`, `shelters.json`, `medical.json`; staging points per run. Rudraprayag: walk 166 nodes / 380 edges (50 bridge edges), drive 89 / 200 (32), both one connected component; walk median 4.8 km/h, 29 km test route 4.5 km/h; 15 shelters, 4 hospitals. | (1) OSMnx 2.x verified: `ox.project_graph`, `ox.add_edge_speeds`, `ox.add_edge_travel_times`. (2) **OSM has no schools/community halls here** (only 17 POIs total, confirmed on two Overpass servers), so when fewer than 5 proper shelters exist we add up to 10 **unverified large-building candidates** (largest likely-pukka Open Buildings on HAND >= 5 m, LSI <= 3, >= 200 m apart) labelled "confirm with authority", plus a warning. (3) Places of worship don't count toward the 5. (4) Third Overpass mirror (maps.mail.ru) added. | | |
| S8 evacuation routing | done (local), not deployed | 2026-10-16 03:00 | `engines/routing.py` (edge closures by flood/bridge/landslide/blocked, adjusted weights, network-simplex assignment with overflow, assembly points), `pipeline/evac.py`; RunResult gets shelters (status/assigned/spare), bridges (first closed hour), capacity gap, assembly points, routes, staging points; `roads.geojson`/`routes.geojson` at `/api/runs/{id}/files/`. 8 mm/h x 4 h: 6,529 to evacuate, 22 usable shelters/assembly points, gap 3,615; disabling S7+A1 -> gap 3,986; block polygon around S7 cuts its intake 371 -> 74. Routing 0.1-0.2 s. Tests 45/45 incl. T10, T11, T12. | RunResult adds `staging_points`, `routes` (top 50 summaries) and `people_to_evacuate`. ETA can be 0 when a demand point snaps to the shelter's own node (sparse network). | **Landslide saturation breaks heavy-rain routing**: at >= ~13 mm/h for 4 h, g = 1.5 lifts most cells to LSI class 5, so ~32,600 people need evacuation, 12/15 shelters are 'landslide_risk' and many roads close (30 mm/h: only 2 usable, gap 32,347). See decision below. | Decide the landslide modulation fix (see report). |
| S9 crowding | done (local), not deployed | 2026-10-16 03:00 | `engines/crowding.py`: POI attractor weights + 0.5 x building count, Gaussian 100 m, p99 normalisation; `crowd` group + `png/crowd.png`; `crowd_e` on every edge (used in S8 weights); top-10 `crowd_hotspots.json` (ranked on unclipped values, attractors within 300 m). | Hotspots are ranked on the unclipped grid (the clipped one ties at 1.0). | Few OSM attractors here, so crowding is mostly building density. | |
| S5/S8 landslide scope (human decision "soften + scope") | done (local) | 2026-10-16 03:40 | Graded g = clip(1 + 0.25 log2(I/I_thr), 0.75, 1.25); demand and shelter exclusion only at class 5; class 4 = cost penalty + "monitor" warning; road closes when >= 20% of its length is class 5; bridges close on reach stage >= cut or flooded approaches. 8 mm/h x 4 h: 2,867 to evacuate, 23 usable shelters, 964 placed, 46 routes. 20-100 mm/h: ~12,000 to evacuate, 7 usable, ~240 placed, ~280/380 walk edges closed by landslide. Tests 46/46. | Spec drift, all in config: `lsi_g_slope/min/max`, `lsi_demand_class`=5 (spec 4), `lsi_shelter_max_class`=4 (spec 3), `lsi_close_share`=0.2 (spec: any cell); bridge depth rule changed. | Heavy rain still closes most hill roads: static LSI near roads is high by construction (distance-to-road factor), so x1.25 lifts road cells to class 5. Options: raise `lsi_close_share`, require static class 5 for closure, or lower the road factor weight. | Optional: pick a further tuning option. |
| S10 forecast + scenarios | done (local), not deployed | 2026-10-16 04:20 | `services/weather.py` (Google Weather API: hourly 240 h paged by 24, daily 10 d, alerts; 10-min in-memory cache; key from env or Secret Manager), series builders (forecast wettest window, worst/best multipliers, CHIRPS historical extreme, manual constant/triangular peak at ceil(H/3)), `GET /api/forecast` (hourly, daily, alerts, worst day, past 90 d IMERG, 10-day screening strip). Live: 240 hourly + 10 daily values (dry October, ~0 mm); historical extreme 201 mm/day -> 50 mm/h x 4 h -> 0.56 km2 flooded; past 90 d: 751 mm, max 81 mm/day. Tests 47/47. | (1) VERIFIED via discovery doc: params `location.latitude/longitude`, `hours`/`days`, `pageSize`/`pageToken`; precip at `precipitation.qpf.quantity` (mm); daily = day + night parts. (2) publicAlerts returns 404 for India -> empty list. (3) Worst day only among days with hourly coverage. (4) IMERG days not yet published -> null. (5) IMD provider not built (S10.3 DECISION; default skip per D4). | Weather API caching terms only partly confirmed (map tiles: 1 h; hourly/daily period not found). We keep raw responses in memory <= 10 min and persist only the run's derived series + label; attribution to Google required in UI. | Confirm Weather API caching terms if storing derived series is a concern. |
| S16 Workspace (Friday part) | built, type-checks, builds; **not visually verified**, not deployed | 2026-10-16 05:00 | React Router (`/`, `/area/:aoiId`); Google Map via `@vis.gl/react-google-maps` + deck.gl `GoogleMapsOverlay`; Terra Draw (rectangle for AOI, polygon for road blocks, click to add shelter); Explore (draw/demo area, size check, name/mode, POST, navigate); Workspace: forecast strip (10-day screening badges + past-90-day chart), layer panel with legends (S16.8 colours), scenario panel bound to ScenarioParams (rain source, day, intensity, duration, shape, river offset, population, walk/drive, start hour, advanced, shelter toggles, add shelter, block road), result cards with tooltips, 2 charts, triage, shelters with capacity bars, routes with passable-until, warnings, compare-with-previous, time slider with play; preparation progress; disclaimer banner + attribution footer. Dev proxy and build verified (`npm run build`, 1.7 MB bundle). | (1) Explore omits history overlays and geocoding search (S11, later). (2) Add shelter uses a browser prompt for capacity. (3) Advisory/Verify/Methods/3D pages and ChatPanel are Saturday (S14-S16 rest). (4) Frontend env var `VITE_GOOGLE_MAPS_API_KEY` (CONFIG.md). | Headless Chrome could not screenshot (page never idles), so the map UI is untested in a real browser. | **Open http://localhost:5173/area/56f044f26351 (with backend on :8080) and check the map, overlays and a run.** |
| Method audit (human: "fix logic and formula gaps") | done (local), not deployed | 2026-10-17 | Self-review of every engine against the literature; 11 fixes, tests 58/58 (new `tests/test_methods.py`). Rudraprayag 4 h sweep (8/20/60/100 mm/h, hist. extreme 27.7 mm/h): flood-exposed 94/145/251/325/165; landslide decisions only above threshold (0 closures/evacuations at 8 and 20 mm/h; 10.8k to evacuate at 60 mm/h); LSI AUC 0.60 on 9 independent records. | (1) **Historical extreme**: wettest H h of the CHIRPS max day by the IMD 1/3 rule `P_H = P_24 (H/24)^(1/3)` (spec spread 24 h of rain over H h: 50 -> 27.7 mm/h). (2) **tc**: Kirpich on the DEM longest flow path with S = relief/L (Kirpich's definition), not Hack + 2 km reach slope. (3) **ARF**: TP-29 areal reduction (Leclerc & Schaake 1972) on rational-method intensity (`apply_arf`). (4) SRC stage = 0 at Q = 0; warning when a reach tops the 30 m curve. (5) **Landslide threshold**: Dahal & Hasegawa (2008) Himalayan I = 73.9 D^-0.79 in the Himalayan arc, Caine elsewhere (`lsi_threshold=auto`). (6) **Modulation**: class shift (-1 below threshold, +1 at >= 2x) replaces graded g (`lsi_modulation`), because x1.25 jumped ~2 narrow classes. (7) **LHASA-style gate**: landslide closures, evacuation demand, shelter exclusion and risk raise only in hours above the threshold; map still shows susceptibility. (8) **Training road factor** from GRIP4 roads in EE (was a constant mean rating); FR may now rate roads. (9) AOI slope/aspect/curvature for LSI computed at 90 m to match training scale. (10) **Depth term** of building risk = JRC Asia residential depth-damage curve (Huizinga 2017), not linear d/3; landslide-raised buildings get R >= 0.5. Clusters use the same risk rule for grid people (incl. landslide). Landslide worst case = max over hours. (11) **Routing**: Tobler per 30 m segment along each walk edge; ETA = crowd-slowed travel time + access walk (risk factors no longer inflate ETAs); routes carry length_km/access_min. Also: re-prepare no longer wipes meta/warnings of skipped steps (`step_warnings`), `prepare_area(force=...)`. | Above threshold, ~35-70% of road edges close (class-5 share >= 0.2; road cuts make near-road cells class 5). Tunable via `lsi_close_share`. GRIP4 licence to confirm. | |
| S14 orchestration (ADK) | done (local), not deployed | 2026-10-16 01:20 | `agents/planner.py` (LlmAgent + output_schema, returns params + diff, human applies), `agents/analyst.py` (LlmAgent + 9 tools, Runner + InMemorySessionService per tab, `new_run_id`), `agents/tools.py` (compact dicts), `/api/plan`, `/api/chat`. Acceptance: plan for "80 mm an hour for 3 hours ..." -> manual/80/3 (unknown shelter name not invented); chat "Which bridge closes first?" calls `list_bridges`, cites B-ids; what-if calls `run_scenario` + `compare_runs`. | Planner uses a reduced `PlanOverrides` schema (no polygons/extra shelters). ADK 2.12 verified: thinking via `BuiltInPlanner`, tools take `ToolContext`. | S14.7 `full_assessment` SequentialAgent not built (optional). | |
| S15 advisory | done (local), not deployed | 2026-10-16 01:30 | `pipeline/facts.py` (id-keyed facts <= 12 KB, validator for ids and numbers incl. headline, rules fallback for 3 horizons), `agents/advisor.py` (Gemini PRO tier, response_schema), `POST/GET /api/runs/{id}/advisory` (background job + Firestore cache; `rules_only`). Tests: validator drops S99 and invented numbers; forced Gemini error -> rules_fallback with 3 horizons. Live: 9-10 grounded recommendations, 0 dropped. | Generation runs in the background (HIGH thinking 50-120 s > Firebase's 60 s rewrite limit); 120 s request timeout. | | |
| S11 history | done (local), not deployed | 2026-10-16 01:40 | `services/history.py`: GFD tiles (getMapId), NASA GLC India points (2,088, cached), AOI events, agreement badge (AOI-only); `agents/historian.py` (google_search only, sources + Search suggestions HTML, Geocoding markers, 30-day refresh); `/api/history/*` (web job in background). Rudraprayag: 0 GFD events in box, 2 GLC points, 10 sourced web leads (2013, 2023 ...). | VERIFIED GFD props: no began/ended -> `system:time_start/end`, `dfo_main_cause`, `dfo_dead`. **Fix:** `gfd_count` now excludes permanent water (GFD `flooded` includes it). | Grounding display terms to confirm. | |
| S12 photo verification | done (local), not deployed | 2026-10-16 01:55 | `api/photos.py`: upload (EXIF GPS or pin, re-encoded JPEG without EXIF), Gemini vision with S12.2 schemas, link building <= 20 m / waterway <= 30 m, overrides applied at run time (S6.3, "verified ..." classes), drain conditions feed S13 priority. Acceptance: openly licensed tin shack photo -> makeshift_or_hut / tin_or_sheet, 0.85, linked; blurred copy -> unclear, not applied (test records deleted). | Overrides are applied per run (not baked into prepare). | Demo photos: owner's own or openly licensed (S12.6 DECISION). | Take 2-3 field-style photos for the demo. |
| S13 urban mode | done (local), not deployed | 2026-10-16 02:20 | `engines/pluvial.py` (Priority-Flood+eps, D8, depressions + watersheds, fill-to-level, drain capacity), `engines/drains.py`; prepare step `urban`; runs add ponding (depth), `ponding_png_url`, `drains` D1-D20; UI layers + Drains tab. Mumbai Kurla-Mithi: 488 depressions, 60 mm/h early-peak 3 h -> 1.7 km2 ponded, 10,869 to move. Tests: volume conservation, fill level, drain ordering. | (1) Fill-to-level instead of the spec's `dep_depth x fill`. (2) **FABDEM bare earth** for all urban terrain (GLO-30 buildings made streets into pits and building edges into "slopes": 79k false landslide evacuations). (3) Rain above `urban_drain_capacity_mm_h` ponds. (4) Urban depth = ponding only; urban bridges ignore river stage. (5) Urban evacuation at 0.5 m still water (DEFRA FD2321), 0.3 m fragile homes. (6) Urban forecast badges vs drain capacity. | No overflow merging between depressions; no river/tide. | |
| Scope fixes (all modes) | done | 2026-10-16 02:10 | **Exposure, evacuation demand, flooded area and drains are limited to the drawn box**; the 3 km grid buffer (hydrology only, no buildings fetched) was being counted as exposed "unattributed" people (cause of the old "only 9% placed in buildings" warning). **Upstream inflow** scenario field (main-stem flow from outside, shared by outside upstream area; Rudraprayag H1 stage 2.6 -> 9.0 -> 15.6 m at 0/3,000/8,000 m3/s). | Spec mentioned inflow but had no field. | | |
| S16 rest + Google design | done (local), not deployed | 2026-10-16 01:45 | Human asked for "Google's exact design philosophy": Material Design 3 rebuild (Google Sans, Material Symbols, GM3 colour tokens light/dark, state layers + ripple, M3 buttons/chips/segmented/slider/switch/tabs/dialog/snackbar/tooltips, emphasized motion), Google Maps-style flow (floating search, layer chips, Maps layer picker, side panel tabs, bottom time bar, Gemini "Ask Pravah" FAB + side sheet). Pages: Advisory (horizons, evidence chips, mini map, print), Verify (dropzone, queue, map), Methods (docs layout, formulas, AHP tables, licences, backtest), 3D. | Theme toggle stored in localStorage (per-viewer convenience). | | |
| S17 deployment | scripts ready, **not deployed** | 2026-10-16 02:00 | `scripts/smoke_test.sh` (passes locally), deploy script sets Firebase CORS + `MIN_INSTANCES`; httpx URL logging silenced (keys were in query strings). | | | Run the deploy + smoke test (hand-off above). |
| S18 demo prep | done (local) | 2026-10-16 02:25 | `scripts/preprocess_demo_aoi.py` (both demo AOIs + run + advisory), `scripts/backtest.py` (GFD POD/FAR/CSI -> `meta.backtest`, shown on Methods). Both boxes have no GFD pixels: reported as such. | | | Record the 3-minute demo video (S18.3). |
| S19 3D view | done (local) | 2026-10-16 02:30 | `api/view3d.py` (DEM float32 mesh, hillshade + depth texture per hour, buildings with ground z, height and run risk), `pages/View3D.tsx` (standalone deck.gl, SimpleMeshLayer terrain + extruded PolygonLayer, exaggeration, time slider). | TerrainLayer did not render in this setup; a custom mesh in UTM metre offsets aligns exactly with buildings. No Google 3D tiles / Elevation API. | | |
| 3D water flow | done (local), not deployed | 2026-10-16 20:30 | `engines/swe.py` (2D shallow water, numba), `pipeline/flow.py` (background job, inflow at entering rivers, HAND comparison), `services/terrain.py` (FABDEM + breaching), `api/flow.py`, `api/view3d.py` (flow ground, Sentinel-2 imagery, per-area buildings + per-run risk), `frontend/src/three/` (scene, shaders, FlowTimeline), `pages/View3D.tsx` rebuilt, Methods "Water flow (3D)". Tests `tests/test_swe.py` (6). | 3D page uses three.js instead of standalone deck.gl (custom water shaders, vertex texture fetch). The flow model is a second model; the brief stays on HAND. | Brief/2D map could switch to the flow model later (changes every demo number and the mandated disclaimer). | Deploy (adds numba to requirements). |
| Policy review | done (local), not deployed | 2026-10-16 | See hand-off. Backend: `services/places.py`, `auth.py`, facts (round_people, deadlines, bottom_line, supplies, road/shelter names), runs API (versions, review, audit, translate, share.txt), aoi API (runs list, official, archive), run fields (start_local, evac_window_h, demand_breakdown/range, gap_range), params (preset_label, visitors, rain_series_override), IMERG hourly; `scripts/event_replay.py`. Frontend: Decision/Analyst (`mode.ts`), Brief page, OfficialStatus, CompareRuns, TimeSlider clock + window, ScenarioPanel presets, LayerPanel gating, offline field check, sign-in (`auth.ts`). Tests `tests/test_policy.py` (10). | Ranges are a what-if band (depth +-30 %, population +-20 %), not a statistical interval. deck.gl overlay is non-interleaved in all browsers (9.4 interleaved race). Approvals without sign-in record typed names as unverified. IMD/CWC entered by staff (no scraping). | Satellite-rain landslide trigger (LHASA-style percentile) not yet built. | Deploy; decide sign-in. |

## Decisions
- `pravah/` has its own git repo (`git init` inside it); the parent home directory is also a git repo, left untouched.
- gcloud/firebase are not on PATH; commands use `~/google-cloud-sdk/bin` and `~/.npm-global/bin`.
- Frontend env var is `VITE_GOOGLE_MAPS_API_KEY` (per CONFIG.md), not SPEC §3.6's `VITE_MAPS_BROWSER_KEY`.
- Budget is ₹9,000 alerts (CONFIG.md), not the $100 in S0.8.
- Dependencies: unpinned list in `backend/requirements.in`, pinned freeze in `backend/requirements.txt`.
- D1 (human): use only `gemini-3.8-flash`. FAST = thinking LOW, PRO = thinking HIGH. Verified on Vertex (global): LOW, MEDIUM, HIGH work; MINIMAL is rejected (400). Env vars: `GEMINI_MODEL_FAST/PRO` both `gemini-3.8-flash`, plus `GEMINI_THINKING_FAST/PRO`.
- Cloud Build needed `cloudbuild.builds.builder`, `storage.objectViewer`, `artifactregistry.writer`, `logging.logWriter` on `265255051442-compute@developer.gserviceaccount.com` (granted by the human).
- No AI co-author lines in commits (human, 2026-10-15).
- Dataset IDs verified in EE: DEM `COPERNICUS/DEM/GLO30_2024_1`, GSW `JRC/GSW1_4` (1_5 absent), WorldPop latest IND year 2020, OpenLandMap clay `b0`. OSMnx 2.1.1 `graph_from_bbox`/`features_from_bbox` take bbox=(W,S,E,N). computePixels/computeFeatures request shapes as in SPEC.
- Landslide modulation: human chose "soften + scope" (16 Oct). Graded g, class-5-only demand/shelter exclusion, share-based road closure, bridge stage/approach rule. Defaults keep the 1 km landslide-record rule.
- Human (16 Oct): "fix logic and formula gaps ... industry research standard" -> method audit (see stage log), plus later
  urban/scope fixes found while testing Mumbai. Human (16 Oct): UI must look and feel like a Google product -> Material 3.
- Landslide modulation changed from graded g (16 Oct "soften + scope") to class shift + LHASA-style rain gate (configurable,
  `lsi_modulation=graded_g` restores the old behaviour).
- Policy review (16 Oct, human "do all" after a critique): Decision view is the default; analysts switch to Analyst view.
- Views merged (16 Oct, human: "merge them both, it confuses the user"): the Decision/Analyst switch is gone; one view shows every control and layer (`mode.ts` deleted). Areas with a run open on the Brief; top bar Brief, Map, 3D, Field check. Roles from sign-in still gate running and approving.
- Rain options audited (16 Oct, human: options must change the simulation with accurate data). Spec deviation: "Early peak" is no longer a linear triangle but the alternating-block design storm on the IMD reduction curve P_t ~ t^(1/3) (Chow et al. 1988), so every k-hour window around the peak holds the IMD k-hour depth; total unchanged. IMD presets are now a `rain_preset` param built server-side (`rainfall.preset_series`; previously a rounded manual intensity). Cloudburst fixed: was 100 mm/h x H through a triangle (4 h = 400 mm, 160 mm/h peak); now peak hour exactly 100 mm, 100 x H^(1/3) mm in H h, always early-peaked. Rain shape hidden where it has no effect (forecast sources, cloudburst). Panel shows the exact hourly series the model receives (`frontend/src/rain.ts` mirrors the backend) and flags settings that differ from the run on the map.
- India map history overlays removed (16 Oct, human: the red areas were mostly rivers and water bodies). Check found the GFD heat map (MODIS 2000-2018) misses Mumbai 2005 and Kerala 2018 and marks ridge pixels 460-600 m above drainage near Rudraprayag as flooded. Explore no longer shows past floods or landslide dots; in an area, "Past incidents" (reported landslides, web reports) draws only once a scenario has run. Open: GFD counts are still an FSI input (`fsi.py` "hist"); masking them by HAND/slope was proposed, not done. (Done overnight: HAND <= 20 m and slope <= 10 deg.)
- Bridges (16 Oct night, human: "closed only when actually closed for construction or water above the bridge height").
  Spec deviation: the spec's single `bridge_cut_stage_m` (3 m for every bridge) is replaced by per-span deck heights
  (HAND at the abutments) and OSM status; approach flooding and landslides no longer close a bridge (the roads beside it
  still close on their own). `bridge_cut_stage_m` kept only so old runs load.
- Landslide road closures use a road-neutral LSI (16 Oct night). Spec deviation: S8.1 used the displayed LSI.
- AI emulator, triggers, drills, CAP alerts, Projects (16 Oct night, human: "real use of AI ... production ready ...
  projects tab"). Triggers come from a physics sweep, not the emulator (emulator thresholds were non-monotone in duration).
  Alerts are CAP status Draft with a non-official sender; never auto-issued.
- Brief headline is deterministic (bottom line); Gemini writes the situation summary and recommendations, still validated.
- Uncertainty is shown as a sensitivity range: demand re-counted with flood depth x0.7/x1.3 and population x0.8/x1.2.
- Every action has one owner from a fixed list of Indian district departments and a model-derived deadline.
- Supplies follow Sphere 2018 minimums (water 15 L/p/d, food 2,100 kcal/p/d, latrine per 20, 3.5 m2, blanket, hygiene kit per 5).
- Place names come from OSM place=* (cached per AOI); Google geocoding is not used for labels (no caching of Maps content).
- Sign-in uses Firebase Authentication (Google accounts) behind `AUTH_REQUIRED` (default false); roles viewer/field/analyst/approver/admin.
- Official IMD/CWC values are typed in by staff and stored with name and time; the app links to IMD, CWC and Google Flood Hub.
- deck.gl GoogleMapsOverlay runs non-interleaved everywhere: 9.4's interleaved mode can create the Deck before the map's GL
  context arrives, leaving a 300x150 canvas (layers clipped); seen in Chrome and Safari.
- Event replays use IMERG V07 hourly rain; the landslide trigger miss in Rudraprayag is published, not tuned away.
- 3D water (16 Oct): a 2D shallow-water model runs per scenario in the background for the 3D view; the brief keeps HAND so
  its numbers and the SPEC disclaimer stay as they are; the 3D panel reports the agreement between the two.
- The flow model and the 3D terrain use FABDEM bare earth (GLO-30 canopy made 15-28 m pits); hilly areas are breached
  4-connected (8-connected cuts are still dams for a face-flux solver), cities keep their hollows.
- Flow inputs mirror the HAND model's: same runoff coefficients, TP-29 ARF over the drawn box, urban drain capacity,
  upstream inflow shared by new outside catchment at entering reaches, river level above normal as rating-curve discharge
  on rivers with >= 100 km2 outside catchment.
- Danger to people uses the DEFRA/EA FD2321 hazard rating (debris factor 0.5 above 0.25 m), drawn in purples so it does
  not clash with red/orange building risk.
- 3D frames are 8-bit (sqrt-coded depth from 1 cm, signed sqrt velocity to 8 m/s), 5-minute steps (10 for storms > 6 h).
