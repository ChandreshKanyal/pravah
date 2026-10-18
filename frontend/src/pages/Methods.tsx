import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getAoiStatus } from "../api/client";
import Disclaimer from "../components/Disclaimer";
import { Icon } from "../components/m3";

const SECTIONS = [
  ["overview", "How Pravah works"], ["flood", "Flood depth"], ["flow", "Water flow (3D)"], ["susceptibility", "Flood susceptibility"], ["exposure", "Exposure and risk"],
  ["routing", "Evacuation routing"], ["forecast", "Rain scenarios"], ["brief", "How the brief is built"], ["ai", "Gemini and guardrails"], ["emulator", "AI emulator and triggers"], ["drill", "Drills and public alerts"], ["fixes", "Fix before the rain"],
  ["governance", "Access and data governance"], ["limits", "Limitations"], ["data", "Data and licences"],
] as const;

const FLOW = [
  { icon: "rainy", t: "Rain", s: "Forecast, record or custom" },
  { icon: "water", t: "Flood depth", s: "Runoff → river stage → HAND" },
  { icon: "groups", t: "Exposure", s: "Buildings & people at risk" },
  { icon: "route", t: "Routing", s: "Shelters within capacity" },
  { icon: "assignment", t: "Advisory", s: "Gemini brief, validated" },
];

const DATA: [string, string, string][] = [
  ["Copernicus DEM GLO-30 (2024)", "Terrain, slope (river mode)", "Copernicus DEM licence: free with attribution (© DLR / Airbus, ESA)"],
  ["FABDEM (Hawker et al. 2022)", "Bare-earth terrain (buildings and forest removed): waterlogging, the water-flow model, the 3D view, and the terrain of areas prepared since 17 Oct", "CC BY-NC-SA 4.0 (non-commercial)"],
  ["MERIT Hydro v1.0.1 (Yamazaki et al. 2019)", "Flow direction, upstream area, HAND", "CC BY-NC 4.0 (non-commercial)"],
  ["Global Flood Database (Tellman et al. 2021)", "Observed floods 2000–2018", "CC BY-NC 4.0 (non-commercial)"],
  ["JRC Global Surface Water 1.4", "Permanent and seasonal water", "Free of charge, without restriction (© EC JRC / Google)"],
  ["Dynamic World V1", "Land cover → runoff coefficient", "CC BY 4.0"],
  ["Sentinel-2 SR (Copernicus)", "NDVI; true-colour picture on the 3D terrain (dry-season median)", "Copernicus data: free and open (contains modified Copernicus Sentinel data)"],
  ["CHIRPS daily", "Rain climatology, record day", "Public domain (CC0)"],
  ["NASA GPM IMERG V07", "Past 90 days of rain; hourly rain for historical event replays", "NASA open data"],
  ["OpenStreetMap place names", "Village, ward and town names in the brief (with Hindi names where mapped)", "© OpenStreetMap contributors, ODbL"],
  ["Sphere Handbook (2018)", "Relief supply minimums in the brief", "Sphere Association; standards cited, not copied"],
  ["WorldPop 100 m", "Population", "CC BY 4.0"],
  ["Google Open Buildings v3 + 2.5D Temporal", "Footprints, heights", "CC BY 4.0 (or ODbL)"],
  ["OpenStreetMap", "Roads, bridges, shelters, POIs", "© OpenStreetMap contributors, ODbL"],
  ["Google Maps Platform Weather API", "10-day forecast", "Google Maps Platform Terms; shown with attribution, not stored"],
  ["Google Maps JavaScript API", "Base map, Street View, traffic (display only)", "Google Maps Platform Terms"],
];

const LIMITS = [
  "HAND flood mapping is a steady-state approximation. It doesn't model water velocity, force, debris, backwater, levee failure or recession. Depths are indicative.",
  "The water-flow model (3D) solves the shallow-water equations on 30 m cells but has no river bathymetry, pipes, culverts or infiltration curve (losses are a constant runoff coefficient), and false dams in narrow gorges are carved away. It is shown next to the brief, which still uses the HAND envelope.",
  "The rational method is designed for small catchments. Applied to the selected area with an envelope (no recession), it gives coarse, conservative estimates; an areal reduction factor softens it for larger catchments.",
  "Resolution: MERIT Hydro is about 90 m and the DEM is 30 m. Single streets and small drains are not resolved. Copernicus GLO-30 is a surface model, including buildings and trees, which matters most in cities.",
  "Building classes are proxies from footprint and height, not confirmed on the ground. Open Buildings heights are model estimates.",
  "Population is a residential estimate (WorldPop). Day/night differences are not modelled; pilgrims and tourists must be entered as a number (they are spread over temples, markets and hotels).",
  "Floods only: landslides, which often come with heavy rain in hill areas, are not assessed.",
  "OpenStreetMap roads and shelters can be incomplete in hill towns. Capacities use footprint × floors × Sphere space standards and must be confirmed locally.",
  "No calibration against gauges.",
  "Licences: MERIT Hydro and the Global Flood Database are non-commercial (CC BY-NC). Commercial use needs other licences or data.",
];

function F({ children }: { children: string }) { return <div className="formula">{children}</div>; }

function Weights({ title, info }: { title: string; info?: { factors: string[]; weights: number[]; cr: number } }) {
  if (!info) return null;
  return (
    <div className="card outlined" style={{ padding: 0 }}>
      <div className="row" style={{ padding: "12px 16px" }}><span className="title-s grow">{title}</span><span className="tag ok">CR {info.cr.toFixed(3)} &lt; 0.10</span></div>
      <table className="tbl"><thead><tr><th>Factor</th><th className="r">AHP weight</th><th style={{ width: "45%" }} /></tr></thead>
        <tbody>{info.factors.map((f, i) => <tr key={f}><td>{f.replace(/_/g, " ")}</td><td className="r">{info.weights[i].toFixed(3)}</td>
          <td><div className="cap"><i style={{ width: `${(info.weights[i] / Math.max(...info.weights)) * 100}%` }} /></div></td></tr>)}</tbody></table>
    </div>
  );
}

export default function Methods() {
  const [sp] = useSearchParams();
  const [meta, setMeta] = useState<Record<string, any> | null>(null);
  const aoi = sp.get("aoi") ?? "56f044f26351";
  useEffect(() => { getAoiStatus(aoi).then((s) => setMeta({ ...(s.meta ?? {}), _name: s.name })).catch(() => setMeta(null)); }, [aoi]);
  const fsi = meta?.fsi ?? { factors: ["hand", "hist", "dist_stream", "upa", "rain", "slope", "C"], weights: [0.236, 0.165, 0.148, 0.148, 0.135, 0.092, 0.077], cr: 0.013 };

  return (
    <div className="doc-page">
      <div className="methods-layout">
        <nav className="toc" aria-label="Contents">
          <span className="label-l muted" style={{ padding: "8px 16px" }}>On this page</span>
          {SECTIONS.map(([id, t]) => <a key={id} href={`#${id}`} className="sl">{t}</a>)}
        </nav>
        <article className="prose">
          <section id="overview">
            <span className="label-l muted">Methods</span>
            <h1 className="headline-l">How Pravah works</h1>
            <p className="body-l muted">Gemini conducts and narrates; deterministic engines compute. Every number on screen comes from the open, documented models below, run on Google Cloud (Earth Engine, Cloud Run, Firestore) with Gemini on Vertex AI for language tasks.</p>
            <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(118px, 1fr))", gap: 8 }}>
              {FLOW.map((s, i) => (
                <li key={s.t} className="card tonal stack-s" style={{ padding: 12, alignItems: "flex-start" }}>
                  <span className="row nowrap" style={{ width: "100%" }}><Icon name={s.icon} className="lg" style={{ color: "var(--primary)" }} />
                    <span className="spacer" /><span className="label-s muted">{i + 1}</span></span>
                  <span className="title-s">{s.t}</span><span className="body-s muted">{s.s}</span>
                </li>
              ))}
            </ol>
            <Disclaimer card />
          </section>

          <section id="flood">
            <h2>Flood depth</h2>
            <p>Rain becomes runoff on each river reach's local catchment, runoff becomes a river stage through a synthetic rating curve, and stage becomes depth wherever the ground is lower than the water: height above nearest drainage (HAND).</p>
            <h3>Runoff (rational method, Kuichling 1889)</h3>
            <F>{"Q = 0.278 · C · i · A · ARF          (m³/s; i in mm/h, A in km²)\nARF = 1 − e^(−1.1·D^0.25) + e^(−1.1·D^0.25 − 0.01·A_mi²)   (TP-29, Leclerc & Schaake 1972)"}</F>
            <p>C is the upstream mean runoff coefficient from Dynamic World land cover (built 0.85, bare 0.60, crops 0.45, trees 0.25 …). The areal reduction factor converts point rain to a catchment average.</p>
            <h3>Timing (Kirpich 1940)</h3>
            <F>{"tc (min) = 0.0195 · L^0.77 · S^−0.385      L = longest flow path (m), S = relief / L"}</F>
            <p>L and the relief come from the DEM flow path inside the area; Hack's law (L = 1.27·A^0.6 km) is the fallback. Discharge ramps up until tc and uses the mean rain over the last tc hours.</p>
            <h3>Stage (Zheng et al. 2018 synthetic rating curve)</h3>
            <F>{"Q(h) = A(h) · R(h)^(2/3) · S^(1/2) / n,   A = V/L,  R = A/P,  P = wetted bed area / L"}</F>
            <p>Volumes and bed areas come from the HAND cells of each reach's catchment (MERIT Hydro, ~90 m), as in NOAA's operational HAND flood mapping. The stage never drops within a scenario (worst-case envelope), and the depth is <span className="mono">max(stage − HAND, 0)</span> on the 30 m grid; permanent water (≥ 90% occurrence) is shown as river, not flood.</p>
          </section>

          <section id="flow">
            <h2>Water flow (3D)</h2>
            <p>The 3D view runs a second, independent model for every scenario: the two-dimensional shallow-water (Saint-Venant) equations, which move water cell by cell according to gravity, pressure, inertia and friction. It shows where water goes, how fast it rises and how fast it flows, minute by minute.</p>
            <F>{"∂h/∂t + ∂(hu)/∂x + ∂(hv)/∂y = R\n∂(hu)/∂t + ∂(hu² + ½gh²)/∂x + ∂(huv)/∂y = −gh ∂z/∂x − g n² u|U| / h^(1/3)\n∂(hv)/∂t + ∂(huv)/∂x + ∂(hv² + ½gh²)/∂y = −gh ∂z/∂y − g n² v|U| / h^(1/3)"}</F>
            <p>h is the water depth, (u, v) the velocity, z the ground, n Manning's roughness by land cover (forest 0.10, built-up 0.08, crops 0.04 …) and R the rain that runs off (the same runoff coefficients as the rational method; in cities, rain beyond the storm-drain capacity) plus river inflow where rivers enter the area.</p>
            <h3>Numerical scheme</h3>
            <p>Finite volumes on the 30 m grid with the HLL Riemann solver (Harten, Lax &amp; van Leer 1983) and hydrostatic reconstruction (Chen &amp; Noelle 2017). Water at rest stays at rest over any terrain, depths never go negative, cells wet and dry, and thin sheets of rain run off steep hillsides at the right speed. Friction is solved implicitly (Xia &amp; Liang 2018), and the time step adapts to the fastest wave (CFL 0.45, typically about 1 s). Water leaves freely through the edge of the area, and none enters through it. Long storms over big areas run on 60 m cells, and the water is then spread back onto the 30 m ground from the lowest cells up.</p>
            <h3>Ground</h3>
            <p>FABDEM bare earth: the surface model's trees turn forest clearings into 15–20 m deep pits. In hilly areas, streams are carved through the false dams that a 30 m grid makes of narrow gorges and bridges (hybrid breaching, Lindsay 2016). Cities keep their hollows, because ponding is the hazard there.</p>
            <h3>Checks</h3>
            <p>Automated tests confirm that still water stays still to machine precision over bumpy terrain with islands; that rain on 5% and 60% slopes reaches the analytical Manning (kinematic-wave) depth; that every run conserves water volume (error about 10⁻¹⁵); and that no water enters through the edge.</p>
            <h3>Danger to people</h3>
            <F>{"HR = d · (v + 0.5) + DF      DF = 0.5 when d > 0.25 m      (DEFRA / Environment Agency FD2321)"}</F>
            <p>Below 0.75: caution. 0.75–1.25: danger for some (children, older people). 1.25–2.0: danger for most. Above 2.0: danger for everyone. The HAND map cannot give this, because it has no velocity.</p>
            <p className="body-s muted">The brief and the 2D map still use the HAND envelope. The 3D panel reports, for each run, how much of the HAND flood area the flow model also floods. The flow model usually adds runoff in streams and gullies that HAND does not map.</p>
          </section>

          <section id="susceptibility">
            <h2>Flood susceptibility</h2>
            <p>A static index of where flooding is most likely, independent of any one storm: height above drainage, past floods, distance to streams, upstream area, rain climate, slope and runoff coefficient, weighted by the Analytic Hierarchy Process (Saaty 1980).</p>
            <Weights title="Flood susceptibility weights (FSI)" info={fsi} />
          </section>

          <section id="exposure">
            <h2>Exposure and risk</h2>
            <p>WorldPop residents are shared among Open Buildings footprints by volume within each ~90 m block. Each building gets a proxy structure class (“likely kaccha”, “likely pukka multi-storey” …) from footprint, height and density.</p>
            <F>{"R_b = 0.5 · D(depth) + 0.3 · F(structure) + 0.2 · P(stream proximity)\nD = JRC depth-damage fraction, Asia residential (Huizinga et al. 2017): 0.5 m → 0.33, 1 m → 0.49, 2 m → 0.72, 6 m → 1.0"}</F>
            <p>Classes: ≥ 0.7 critical, 0.5–0.7 high, 0.3–0.5 moderate.</p>
          </section>

          <section id="routing">
            <h2>Evacuation routing</h2>
            <p>OpenStreetMap walking and driving networks are sampled every 30 m against the hourly depth grid. A road closes when water exceeds the walking (0.5 m) or vehicle (0.3 m) limit, or when you block it.</p>
            <h3>Bridges</h3>
            <p>Bridges are the real spans mapped in OpenStreetMap (not the merged road segments of the routing graph, which can run for kilometres). Each span's deck height above the normal river level is the height above drainage (HAND) at its two abutments, where the road meets the deck; the lower end counts. A bridge closes only when the river stage of the reach it crosses reaches its deck (minus an optional safety margin), or from the first hour when OpenStreetMap marks it under construction, disused or closed. The 30 m terrain cannot resolve decks lower than 3 m, so lower decks are set to 3 m and flagged. Flyovers over roads and railways never close on river stage.</p>
            <F>{"walk speed (Tobler 1993) = 6 · e^(−3.5·|tanθ + 0.05|) km/h, per 30 m segment\nassignment: min Σ people × time, subject to shelter capacity (network simplex, with an 'unplaced' overflow)"}</F>
            <p>Route ETAs are real travel times (crowding-slowed) plus the walk to the network; a steep-slope penalty only steers route choice. Shelters are “reachable in this scenario” if dry and connected. Capacity uses 3.5 m² per person (Sphere).</p>
          </section>

          <section id="forecast">
            <h2>Rain scenarios</h2>
            <ul>
              <li><b>Forecast</b>: the wettest hours of a chosen day from the Google Maps Platform Weather API (10 days); <b>Worst</b> multiplies it.</li>
              <li><b>Record</b>: the wettest day nearby in CHIRPS 2001–2024; its wettest H hours follow the IMD reduction formula <span className="mono">P_H = P_24 · (H/24)^(1/3)</span>.</li>
              <li><b>Custom</b>: a steady or early-peak storm you set, or an IMD category: heavy (top of band, 115.5 mm/day), very heavy (204.4), extremely heavy (300), each over its wettest H hours by the reduction rule; a cloudburst is exactly 100 mm in its peak hour (IMD definition), 100 · H<sup>1/3</sup> mm over H hours.</li>
              <li><b>Early peak</b> is the alternating-block design storm (Chow, Maidment &amp; Mays 1988) on the same reduction curve: the wettest k hours around the peak hold the IMD k-hour depth, so a 4 h storm puts 63% of its rain in the peak hour.</li>
            </ul>
            <p>The 10-day strip screens each day with a one-reach model; run the full scenario for detail. The past 90 days come from NASA GPM IMERG.</p>
            <p><b>Upstream river flow</b> adds water that enters the area from outside (for example a CWC flood forecast for a main river): it is shared across reaches by their upstream area outside the box, so the main stem carries all of it.</p>
            <h3>One model for every area (no mode to choose)</h3>
            <p>Every area gets river flooding and street waterlogging. Which physics applies where is decided per cell and per channel from the data, never by a label or by AI:</p>
            <ul>
              <li><b>River flooding</b> (HAND stage) only on channels where a rain-driven rating curve means something: not <b>tidal</b> (a channel lying within 1.5 m of sea level follows the sea), not a one-cell stub, and not an <b>urban drain</b> (a channel under 100 km² whose catchment is at least half built-up: its engineered walls and bed are invisible to 90 m terrain, and its overflow is the street waterlogging below, so it is not counted twice). A channel whose stage reaches the top of its rating curve in a run is left out of that run.</li>
              <li><b>Street waterlogging</b> in hollows of the bare-earth terrain whose catchment is at least 30% built-up (Dynamic World): rain beyond the storm-drain capacity fills them. In fields and forest rain soaks in through the runoff coefficient.</li>
              <li>The flood depth is the <b>deeper</b> of river and waterlogging depth in each cell; bridges close when the river reaches the deck or their approaches flood.</li>
              <li>People move where the flood hazard rating (DEFRA/EA FD2321, depth × (speed + 0.5) + debris) reaches “danger for some”: river water moves at the Manning speed of its channel; standing water has no speed, which gives 0.5 m (0.3 m in fragile homes).</li>
            </ul>
            <F>{"filled = PriorityFlood+ε(FABDEM)   (Barnes et al. 2014)\nV_in = C_ws · Σ max(0, i − drain capacity) · A_ws   → fill each built-up hollow to the level that holds V_in\ndepth = max(river HAND depth on reliable channels, waterlogging depth)"}</F>
            <p>The storm-drain capacity is 25 mm/h (Mumbai's historical standard; configurable) and applies under built-up land, in the waterlogging screen and the water-flow model alike. A one-line profile of each area (built-up share, slopes, largest river) is shown above the scenario; it sets display defaults and never switches a hazard off. Tides and storm surge are not modelled. Drains and culverts are ranked for pre-monsoon clearing by flow accumulation, ponding or flood susceptibility, and exposed people within 300 m.</p>
          </section>

          <section id="brief">
            <h2>How the brief is built</h2>
            <ul>
              <li><b>Bottom line first.</b> The headline is written by rules from the model numbers: who must move, from which places, by when, and how many have no shelter place. Gemini adds a short situation summary whose numbers are checked.</li>
              <li><b>Rounded figures with a range.</b> People are rounded (to 5, 10, 50 or 100 depending on size). The range re-counts who must move if flood depths are 30% lower or higher and the population 20% lower or higher: a what-if band for uncalibrated models, not a statistical interval.</li>
              <li><b>Places, not codes.</b> Clusters, bridges, routes and shelters carry the nearest OpenStreetMap village, ward or town name and a nearby named landmark.</li>
              <li><b>Owner and deadline per action.</b> Each action names one responsible department (Revenue, Police, PWD, Health, SDRF, municipal body…). Deadlines come from the model: a bridge must close before the hour it is cut, people must move before the first evacuation route is cut, teams are staged before the rain starts. Forecast scenarios show clock times; hypothetical rain shows hours after the rain starts.</li>
              <li><b>Supplies.</b> Water (15 L per person per day), food (2,100 kcal per person per day), latrines (1 per 20 people), covered space (3.5 m² per person), blankets and hygiene kits, from the Sphere Handbook minimums, for the central estimate and the high end of the range.</li>
              <li><b>Accountability.</b> Every generated brief is an immutable numbered version. It moves from Draft to Reviewed to Approved with a name, designation and time; approved versions are locked and every action is logged.</li>
              <li><b>Languages and sharing.</b> Hindi is produced by Gemini; any item whose numbers change in translation stays in English. A plain-text version works on WhatsApp, SMS and 2G connections.</li>
              <li><b>Official warnings.</b> Staff enter the IMD district colour code and the CWC gauge level, shown next to the model with links to IMD, CWC and Google Flood Hub. Pravah does not scrape these sites.</li>
            </ul>
          </section>

          <section id="ai">
            <h2>Gemini and guardrails</h2>
            <ul>
              <li><b>Scenario planner</b> (ADK agent with a typed output schema) turns a sentence into settings; you review the changes and apply them.</li>
              <li><b>Ask Pravah</b> (the assistant on every page; ADK agent with tools) answers general questions only from Google Search results (sources shown), finds places with Google geocoding, reads an open area's results through the same engines, and is told never to state a number it did not get from a tool. Anything it would do in the app (move the map, open a view, prepare an area, run a scenario, switch layers) is shown as a proposal you confirm; it cannot act on its own.</li>
              <li><b>Advisory brief</b>: Gemini drafts recommendations from a compact facts sheet. A validator drops any recommendation that cites an unknown id or a number not in its cited facts, and fills empty horizons from deterministic rules; if Gemini fails, a rules-based brief is produced.</li>
              <li><b>Web incidents</b>: a separate agent with Google Search grounding returns sourced leads, shown with Google Search suggestions and labelled unverified.</li>
            </ul>
          </section>

          <section id="emulator">
            <h2>AI emulator and rain triggers</h2>
            <p>The 2D water model takes about a minute per storm. For each area Pravah trains an emulator on about 100 runs of it: 64 storms from a scrambled Sobol design over duration (1–6 h), size (the wettest hours of a 40–450 mm day), timing (steady or early peak) and river level (0–3 m, river areas), plus a sweep of 12 storm sizes at 1, 3 and 6 hours. The emulator then answers in milliseconds, so the rain can be dragged and the flood redrawn live.</p>
            <F>{"peak depth field  ≈  mean + Σ_k a_k(storm) · φ_k          (proper orthogonal decomposition, ≥ 99.9% of variance, ≤ 12 patterns)\na_k(storm) = thin-plate-spline RBF of [rain above drain capacity, its peak hour, total rain, duration, river level]"}</F>
            <p>Every storm is predicted by an emulator that never saw it (leave-one-out) and scored against the 2D model: the share of wet area both agree on (critical success index) and the depth error. Mumbai: median 97% agreement (90th-percentile worst case 87%), median depth error 1.5 cm; the misses are storms just at the drain capacity, where only a few streets get wet. Outside the trained range the emulator holds the storm at the nearest trained value and says so. The emulator is a what-if aid; routes, shelters and the brief always come from a full scenario.</p>
            <h3>Rain triggers for early action</h3>
            <p>For each OpenStreetMap village or neighbourhood, the smallest early-peaked storm (mm in 1, 3 and 6 hours) that puts at least 25 people, or 5% of its residents, in water 30 cm deep or more at home. Computed with the 2D model itself (the 12-size sweep, interpolated between the two sizes that bracket each place), not the emulator. Each threshold is also expressed as the IMD 24-hour category it belongs to, so a district can agree in advance which IMD warning colour triggers action in which place. River at its normal level: a river already running high lowers every threshold.</p>
          </section>

          <section id="drill">
            <h2>Tabletop drills and public alerts</h2>
            <p><b>Drills.</b> Gemini acts as the exercise controller of a mock exercise on any stored scenario. A deterministic timeline from the model (rain per hour, bridges and roads closing, routes cut, the move-before deadline, the shelter gap, the peak) is turned into 7–9 timed messages from plausible offices. Messages from the model must cite fact ids and quote only numbers from the facts (checked; others are dropped); two are invented friction (a rumour, a power cut at a shelter) and are labelled “exercise inject”. Each typed decision is scored 0–3 against the expected actions and the facts, and the drill ends with an after-action report: strengths, gaps, changes for the SOP and training needs. Without Gemini a rule-based drill runs.</p>
            <p><b>Public alerts.</b> A draft in the Common Alerting Protocol (CAP 1.2), the format of NDMA's SACHET integrated alert system: headline, description, instruction and a 160-character SMS in English and Hindi, written by Gemini from the facts (numbers checked; the Hindi must carry the same digits, else template text), the flooded area at the worst hour as alert polygons, and CAP severity, urgency and certainty from the results (forecast rain: likely; what-ifs: possible). Status is always Draft, the sender is marked as not official, and the note says to issue only through SACHET or the authorised state channel after review.</p>
          </section>

          <section id="fixes">
            <h2>Fix before the rain</h2>
            <p>At the end of area preparation Pravah lists places where maintenance would most reduce flooding, each with the evidence it rests on. Three kinds of evidence are kept apart, because they are not equally strong:</p>
            <p><b>Reported on the web.</b> Gemini with Google Search lists spots in the box that municipal lists or news name as repeatedly waterlogged. A link is kept only if its site is among the pages Search returned; places are positioned with Google geocoding (vague results such as a whole suburb are dropped) and compared with our terrain model (low ground or a road hollow nearby).</p>
            <p><b>Seen from space.</b> Only open data that may be analysed: Copernicus Sentinel-2 (10 m) and Google Dynamic World. Mapped rivers and canals whose surface reads as vegetation (NDVI ≥ 0.35 in recent clear scenes; culverted stretches excluded) suggest weeds or silt; land that turned built-up since 2016–17 on former water or wetland, or under 2 m above a stream within 150 m, and new bare ground near streams, suggest encroachment or dumped muck. Gemini looks at the image clips (true and false colour, or before and after) and says whether they show the claim; leads it says the images contradict are dropped.</p>
            <p><b>Model estimate.</b> Culverts and drain crossings (OpenStreetMap) ranked by the water arriving from upstream and the people on low ground within 400 m; road hollows in built-up parts of the bare-earth terrain that fill first; and road links that are the only drivable way out for a neighbourhood (graph bridges) on low ground or over a stream.</p>
            <p><b>What it cannot do.</b> 10 m imagery cannot show a blocked drain, a rubbish pile or parked cars, and Google satellite and Street View images may not be analysed by AI under the Maps terms. Those checks need eyes on site: each item opens Google imagery (Look closer, Street View) for a person to look at; Pravah never analyses it.</p>
          </section>

          <section id="governance">
            <h2>Access and data governance</h2>
            <ul>
              <li><b>Sign-in and roles.</b> With sign-in enabled (Firebase Authentication with Google accounts), roles are viewer, analyst, approver and admin. Running scenarios and using Gemini need the analyst role; approving a brief needs the approver role.</li>
              <li><b>Sensitive outputs.</b> Building-level risk (the 3D buildings) is served only to signed-in users when sign-in is enabled, because labels like “critical risk” on individual houses can affect residents.</li>
              <li><b>Audit trail.</b> Brief generation, reviews, approvals, translations, official-status entries and area archiving are logged with the user, time and version.</li>
              <li><b>Where data lives.</b> Model inputs and outputs stay in this Google Cloud project (Cloud Storage, Firestore). Google Maps content is display only.</li>
            </ul>
          </section>

          <section id="limits">
            <h2>Limitations</h2>
            {meta?.backtest && (
              <div className="notice info"><Icon name="fact_check" />
                <span><b>Backtest for {meta._name}</b> ({meta.backtest.scenario}): {meta.backtest.result} {meta.backtest.note}.</span></div>
            )}
            <ol style={{ margin: 0, paddingLeft: 22, display: "flex", flexDirection: "column", gap: 8 }}>{LIMITS.map((l, i) => <li key={i} className="body-m">{l}</li>)}</ol>
          </section>

          <section id="data">
            <h2>Data and licences</h2>
            <div className="card outlined" style={{ padding: 0, overflowX: "auto" }}>
              <table className="tbl"><thead><tr><th>Dataset</th><th>Used for</th><th>Licence / terms</th></tr></thead>
                <tbody>{DATA.map(([d, u, l]) => <tr key={d}><td><b>{d}</b></td><td>{u}</td><td className="body-s">{l}</td></tr>)}</tbody></table>
            </div>
            <p className="body-s muted">Google Maps content is used only for display, forecasts and the search box (Maps Platform Terms §3.2.3): never scraped, cached beyond what the terms allow, or used as model input. Earth Engine is used under the noncommercial tier.</p>
          </section>
        </article>
      </div>
    </div>
  );
}
