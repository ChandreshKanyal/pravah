# Pravah: submission text (AI Builder Cup 2026)

## Brief description (for the submission form)

**Pravah** helps a district disaster officer in India answer three questions before and during a flood: *where will the
water go, who has to move, and where can they go safely in time?* Draw a box of up to 10 km anywhere in India (or pick
one of five prepared areas) and Pravah builds a flood model of it in about two minutes, from open data: 30 m terrain and
rivers, 24 years of satellite rainfall, past floods seen from space, OpenStreetMap roads, Google Open Buildings and
population. An official then runs a scenario: the live 10-day forecast, a real past storm replayed from NASA satellite
rain, a 1-in-100-year day, an IMD rain category or a cloudburst, with the river already high, pilgrims present or
shelters closed. Pravah simulates the water hour by hour (a 2D flow model and a height-above-drainage model), closes
roads and bridges as they flood, and assigns people to the nearest shelter that stays dry and reachable, within its
capacity. The result is a map, a 3D view, evacuation routes with a "leave before" time for each, and a brief for the
District Magistrate. Every output is a first draft for official review.

**How Google Cloud and Gemini are used**

- **Gemini (gemini-3.8-flash on Vertex AI, with the Agent Development Kit)** does the reasoning and writing, always from
  the model's own numbers:
  - **Ask Pravah:** an ADK assistant that answers questions about the scenario and proposes runs. It uses tools over the
    stored results, and the official confirms before anything runs.
  - **The brief:** written at high thinking, grouped by department, with priorities and deadlines. A validator checks
    every shelter, road and number against the run, and rule-based text is the fallback.
  - **Choice explanations:** a plain-words explanation of why each shelter and route was chosen, from flood depth,
    height above nearby water (the IS 14264 plinth rule), isolation (ARC 4496), distance and Sphere floor space.
  - **Alerts and translation:** public alerts in the Common Alerting Protocol (CAP 1.2) format, in English and Hindi,
    and Hindi versions of the brief.
  - **Grounded web search:** waterlogging spots and past floods reported on the web, found with Google Search
    grounding and cited.
  - **Drills:** a tabletop exercise run by Gemini against the simulated timeline.
- **Cloud Run** hosts the FastAPI backend (Python: the flow model compiled with numba, road routing, shelter
  assignment), with 8 CPUs for the simulations.
- **Firestore** stores areas, scenario runs and their history, background run jobs, briefs and their versions,
  review decisions, alerts, drills and an audit log. **Cloud Storage** holds the area rasters, flood depths and 3D
  frames.
- **Firebase Hosting** serves the React and Material 3 website, which calls Cloud Run directly. Firebase
  Authentication with roles (viewer to approver) is built in and switched off for judging.
- **Earth Engine** supplies the terrain (Copernicus DEM, MERIT Hydro), rainfall (CHIRPS, NASA GPM IMERG), surface water
  history (JRC) and land cover. **Google Open Buildings** supplies the buildings. **Google Maps Platform** supplies the
  map display, Street View, place search and the weather forecast. No Maps imagery is ever given to the AI.

## Showcase areas (prepared 18 Oct; open from the home page under "Try a prepared area")

| Area | Scenario (the run each one opens on) | Why |
|---|---|---|
| Rudraprayag, Uttarakhand | Cloudburst: 100 mm in one hour, 15,000 pilgrims on the Char Dham route | Alaknanda-Mandakini confluence; 1998 and 2013 disasters |
| Chennai Adyar-Velachery | Live forecast: the wettest day of the next 10 (northeast monsoon active since ~15 Oct) | Low-lying city, floods of 2015, 2021 and 2023 |
| Mumbai Kurla-Mithi | Real event replay: 26 July 2005 (NASA IMERG rain of that day) | The Mithi overflowed into Kurla; Mumbai's wettest day (944 mm at Santacruz) |
| Puri, Odisha | Worst case: IMD extremely heavy rain (238 mm in 12 h, early peak) with 50,000 Rath Yatra visitors | Coastal pilgrim town, few mapped shelters; its own 1-in-100-year day from satellite rain is only 122 mm |
| Silchar, Assam | Everything at once: June 2022 rain x1.5, Barak 4 m high, 12,000 m3/s upstream | 90% of the city was under water in June 2022 |

Results of the showcase runs (live backend, 18 Oct ~14:55 IST; area id / run id):

- **Rudraprayag** `56f044f26351` / `34be95ff18e8`: 144 mm in 3 h; 1,273 people to move, 900 without a reachable
  shelter; 5.2 km2 flooded (flow model).
- **Chennai** `7a7c41e90681` / `fde83a1deee6`: forecast for Wed 21 Oct, 31 mm in 6 h; 2,131 to move, all placed;
  0.6 km2. The saved run keeps this forecast; a new run uses the forecast of the day it is run.
- **Kurla** `d277268c1783` / `6536e0837c14`: IMERG 317 mm that day (the Santacruz gauge had 944 mm; a 10 km satellite
  pixel smooths the peak), 303 mm in the wettest 12 h; 29,607 to move, all placed; 3.3 km2.
- **Puri** `66bc06eb21cb` / `d0d466f9b2ea`: 238 mm in 12 h, peak 104 mm/h; 17,927 to move, 948 without a shelter;
  17.6 km2.
- **Silchar** `90ee5d445ddf` / `731fa6e0d7a0`: 200 mm in 24 h; 108,420 to move, 103,534 without a shelter; 19.9 km2.

## Video script (3-4 min; screen recording of the live site, voice-over)

Record on the deployed site after one warm-up visit (the first visit after a quiet spell takes ~15 s to wake the server).
Keep the browser at 1440x900, light theme, and open each showcase area once beforehand so every picture is cached.

| Time | On screen | Voice-over |
|---|---|---|
| 0:00-0:20 | Home page, India map, the five prepared areas | "Every monsoon, district officers in India decide in hours who must move and where to. Pravah gives them a first draft of that plan, built from open data and Gemini, for any place in India." |
| 0:20-0:45 | Draw a box over a town; the Gemini-style "Analysing this area" panel ticks through terrain, rain history, roads, buildings, shelters | "Draw an area up to 10 km. In about two minutes Pravah reads 30 m terrain and rivers, 24 years of satellite rain, past floods seen from space, OpenStreetMap roads and Google Open Buildings, and finds schools and halls that can shelter people." |
| 0:45-1:20 | Open Rudraprayag; the cloudburst run; press play on the hours; flood spreads; roads turn red | "Here is Rudraprayag on the Char Dham route, with a cloudburst: 100 mm in one hour while 15,000 pilgrims are in town. Pravah simulates the water hour by hour, closes roads and bridges as they flood, and counts who is in the way: about 1,300 people, and 900 of them have no reachable shelter. That gap is the first thing an officer needs to know." |
| 1:20-1:50 | Click a shelter: the card with Gemini's explanation and the checks (dry, 0.6 m above nearby water, door roads open, distance, room); click a route | "Why this shelter? Gemini explains each choice from the model's own numbers: it stays dry, it stands above the nearby water by the Indian Standards plinth rule, its roads stay open, and it has room. Every route has a leave-before time." |
| 1:50-2:15 | Switch to 3D; tilt; flood frames play over satellite imagery | "The same scenario in 3D: the 2D flow model every five minutes over the real terrain, with buildings and shelters." |
| 2:15-2:45 | Open Silchar: the everything-at-once run; Brief page | "Silchar, where 90 percent of the city went under water in 2022. June 2022's rain, half again, the Barak already 4 m high. Over 100,000 people at risk. Gemini drafts the brief for the District Magistrate by department, with priorities and deadlines, and every number is checked against the model before it is shown." |
| 2:45-3:10 | Ask Pravah (the spark button): "What if the evacuation starts two hours later?"; the proposed run with a Run button | "Officials can ask in plain words. The Gemini agent reads the results, proposes a new scenario and waits for the human to run it." |
| 3:10-3:30 | Chennai live forecast; Fixes list; the CAP alert in English and Hindi | "Chennai runs on this week's live forecast. Pravah also lists pre-monsoon fixes, drains and low spots to clear, and drafts public alerts in the national CAP format, in English and Hindi." |
| 3:30-3:50 | Architecture slide: Firebase Hosting, Cloud Run, Firestore, Vertex AI Gemini + ADK, Earth Engine, Maps Platform | "Pravah runs on Firebase Hosting and Cloud Run, stores every run in Firestore, and uses Gemini on Vertex AI with the Agent Development Kit. It is decision support: every output is a draft for official review." |
