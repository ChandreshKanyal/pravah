import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getAoiStatus } from "../api/client";
import Disclaimer from "../components/Disclaimer";
import { Icon } from "../components/m3";

const SECTIONS = [
  ["overview", "How Pravah works"], ["flood", "Flood depth"], ["landslide", "Landslide susceptibility"], ["exposure", "Exposure and risk"],
  ["routing", "Evacuation routing"], ["forecast", "Rain scenarios"], ["brief", "How the brief is built"], ["ai", "Gemini and guardrails"],
  ["track", "Track record"], ["governance", "Access and data governance"], ["limits", "Limitations"], ["data", "Data and licences"],
] as const;

const FLOW = [
  { icon: "rainy", t: "Rain", s: "Forecast, record or custom" },
  { icon: "water", t: "Flood depth", s: "Runoff → river stage → HAND" },
  { icon: "landslide", t: "Landslides", s: "Susceptibility × rain trigger" },
  { icon: "groups", t: "Exposure", s: "Buildings & people at risk" },
  { icon: "route", t: "Routing", s: "Shelters within capacity" },
  { icon: "assignment", t: "Advisory", s: "Gemini brief, validated" },
];

const DATA: [string, string, string][] = [
  ["Copernicus DEM GLO-30 (2024)", "Terrain, slope (river mode), 3D view", "Copernicus DEM licence: free with attribution (© DLR / Airbus, ESA)"],
  ["FABDEM (Hawker et al. 2022)", "Bare-earth terrain in urban mode (buildings and forest removed)", "CC BY-NC-SA 4.0 (non-commercial)"],
  ["MERIT Hydro v1.0.1 (Yamazaki et al. 2019)", "Flow direction, upstream area, HAND", "CC BY-NC 4.0 (non-commercial)"],
  ["Global Flood Database (Tellman et al. 2021)", "Observed floods 2000–2018", "CC BY-NC 4.0 (non-commercial)"],
  ["JRC Global Surface Water 1.4", "Permanent and seasonal water", "Free of charge, without restriction (© EC JRC / Google)"],
  ["Dynamic World V1", "Land cover → runoff coefficient", "CC BY 4.0"],
  ["Sentinel-2 SR (Copernicus)", "NDVI", "Copernicus data: free and open"],
  ["OpenLandMap soil clay", "Landslide factor", "CC BY-SA 4.0"],
  ["CHIRPS daily", "Rain climatology, record day", "Public domain (CC0)"],
  ["NASA GPM IMERG V07", "Past 90 days of rain; hourly rain for historical event replays", "NASA open data"],
  ["OpenStreetMap place names", "Village, ward and town names in the brief (with Hindi names where mapped)", "© OpenStreetMap contributors, ODbL"],
  ["Sphere Handbook (2018)", "Relief supply minimums in the brief", "Sphere Association; standards cited, not copied"],
  ["WorldPop 100 m", "Population", "CC BY 4.0"],
  ["Google Open Buildings v3 + 2.5D Temporal", "Footprints, heights", "CC BY 4.0 (or ODbL)"],
  ["NASA Global Landslide Catalog", "Landslide inventory", "NASA open data (terms being confirmed)"],
  ["GRIP4 global roads (Meijer et al. 2018)", "Road factor in the landslide training box", "Terms being confirmed"],
  ["OpenStreetMap", "Roads, bridges, shelters, POIs", "© OpenStreetMap contributors, ODbL"],
  ["Google Maps Platform Weather API", "10-day forecast", "Google Maps Platform Terms; shown with attribution, not stored"],
  ["Google Maps JavaScript API", "Base map, Street View, traffic (display only)", "Google Maps Platform Terms"],
];

const LIMITS = [
  "HAND flood mapping is a steady-state approximation. It doesn't model water velocity, force, debris, backwater, levee failure or recession. Depths are indicative.",
  "The rational method is designed for small catchments. Applied to the selected area with an envelope (no recession), it gives coarse, conservative estimates; an areal reduction factor softens it for larger catchments.",
  "Resolution: MERIT Hydro is about 90 m and the DEM is 30 m. Single streets and small drains are not resolved. Copernicus GLO-30 is a surface model, including buildings and trees, which matters most in cities.",
  "Building classes are proxies from footprint and height until verified by field photos. Open Buildings heights are model estimates.",
  "Population is a residential estimate (WorldPop). Day/night differences are not modelled; pilgrims and tourists must be entered as a number (they are spread over temples, markets and hotels).",
  "Landslide output is susceptibility, not prediction. The rain trigger uses a published regional threshold (Dahal & Hasegawa 2008 in the Himalaya, Caine 1980 elsewhere) without antecedent rain. The landslide inventory is incomplete.",
  "OpenStreetMap roads and shelters can be incomplete in hill towns. Capacities use footprint × floors × Sphere space standards and must be confirmed locally.",
  "No calibration against gauges. Event replays test the rain trigger against a handful of catalogued events; they are evidence, not validation.",
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

const DEMO_IDS = ["56f044f26351", "d277268c1783"];

function TrackRecord() {
  const [rows, setRows] = useState<{ name: string; ev: any[] }[] | null>(null);
  useEffect(() => {
    Promise.all(DEMO_IDS.map((id) => getAoiStatus(id).then((s) => ({ name: s.name ?? id, ev: (s.meta?.event_replays as any[]) ?? [] })).catch(() => ({ name: id, ev: [] }))))
      .then(setRows);
  }, []);
  if (!rows) return <div className="shimmer" style={{ height: 120 }} />;
  if (!rows.some((r) => r.ev.length)) return <p className="body-m muted">Event replays have not been run yet (scripts/event_replay.py).</p>;
  return (
    <>
      {rows.filter((r) => r.ev.length).map((r) => (
        <div key={r.name} className="card outlined" style={{ padding: 0, overflowX: "auto" }}>
          <div className="title-s" style={{ padding: "12px 16px 4px" }}>{r.name}
            <span className="body-s muted"> · landslide trigger reached in {r.ev.filter((e) => e.trigger_fired).length} of {r.ev.length} recorded events</span></div>
          <table className="tbl">
            <thead><tr><th>Event and record</th><th className="r">Observed rain (IMERG)</th><th>Landslide trigger</th><th className="r">Model: people to move</th><th>Same monsoon: other days over the 24 h trigger</th></tr></thead>
            <tbody>{r.ev.map((e) => (
              <tr key={e.id}>
                <td><b>{e.label}</b><div className="body-s muted">{e.record}</div></td>
                <td className="r">{e.window_mm} mm in 12 h<div className="body-s muted">peak {e.imerg_peak_mm_h} mm/h · 48 h {e.imerg_48h_mm} mm</div></td>
                <td>{e.trigger_fired ? <span className="tag high">fired (×{e.trigger_ratio_max})</span> : <span className="tag">not reached (×{e.trigger_ratio_max ?? "–"})</span>}
                  {e.glc_point_class != null && <div className="body-s muted">class {e.glc_point_class} at the record point; {Math.round(100 * e.share_class4plus_within_1km)}% of land within 1 km in class 4–5</div>}</td>
                <td className="r">{(e.people_to_move ?? 0).toLocaleString("en-IN")}<div className="body-s muted">{e.flooded_km2} km² flooded</div></td>
                <td>{e.season ? `${e.season.days_over_24h_trigger} of ${e.season.days} days (≥ ${e.season.trigger_24h_mm} mm); event day ranked ${e.season.event_day_rank ?? "–"} with ${e.season.event_day_mm ?? "–"} mm` : "–"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ))}
    </>
  );
}

export default function Methods() {
  const [sp] = useSearchParams();
  const [meta, setMeta] = useState<Record<string, any> | null>(null);
  const aoi = sp.get("aoi") ?? "56f044f26351";
  useEffect(() => { getAoiStatus(aoi).then((s) => setMeta({ ...(s.meta ?? {}), _name: s.name })).catch(() => setMeta(null)); }, [aoi]);
  const fsi = meta?.fsi ?? { factors: ["hand", "hist", "dist_stream", "upa", "rain", "slope", "C"], weights: [0.236, 0.165, 0.148, 0.148, 0.135, 0.092, 0.077], cr: 0.013 };
  const lsi = meta?.lsi ?? { factors: ["slope", "rain", "ndvi", "drain", "road", "soil", "curv", "aspect"], weights: [0.206, 0.19, 0.13, 0.107, 0.107, 0.107, 0.091, 0.063], cr: 0.01 };

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

          <section id="landslide">
            <h2>Landslide susceptibility</h2>
            <p>Eight factors (slope, rain climate, NDVI, distance to streams, distance to roads, soil clay, curvature, aspect) are classed and rated, then weighted by the Analytic Hierarchy Process (Saaty 1980). Ratings come from Frequency Ratio (Lee & Pradhan 2007) when at least 15 well-located past landslides exist within 50 km, otherwise from expert ratings. Scores are scaled and classed by the 100 km training region so areas are comparable; the AOI's terrain is computed at the same 90 m scale as the training data.</p>
            <F>{"LSI = Σ w_f · r_f(class_f)          FR_k = (slides in k / all slides) / (cells in k / all cells)"}</F>
            <div className="grid-2"><Weights title="Landslide factor weights" info={lsi} /><Weights title="Flood susceptibility weights (FSI)" info={fsi} /></div>
            {meta?.lsi?.auc != null && <p className="body-m muted">For {meta._name}: {meta.lsi.method === "expert" ? "expert ratings" : "frequency-ratio ratings"} from {meta.lsi.landslide_records} landslide records; ROC AUC {meta.lsi.auc} ({meta.lsi.auc_kind}).</p>}
            <h3>Rain trigger (decision gate)</h3>
            <F>{"I_thr(D) = 73.90 · D^−0.79   Himalaya (Dahal & Hasegawa 2008)      I_thr(D) = 14.82 · D^−0.39   elsewhere (Caine 1980)\nR(t) = mean rain over hours 1..t / I_thr(t)\nclass(t) = static class − 1 if R < 1;  + 1 if R ≥ 2"}</F>
            <p>Following NASA's LHASA nowcast logic, landslide closures, evacuations and shelter exclusions only apply in hours when rain exceeds the threshold. Below it, slopes are shown as susceptibility with a “monitor” note. This is susceptibility, never a timed prediction.</p>
          </section>

          <section id="exposure">
            <h2>Exposure and risk</h2>
            <p>WorldPop residents are shared among Open Buildings footprints by volume within each ~90 m block. Each building gets a proxy structure class (“likely kaccha”, “likely pukka multi-storey” …) from footprint, height and density, replaced by a field-photo class when verified.</p>
            <F>{"R_b = 0.5 · D(depth) + 0.3 · F(structure) + 0.2 · P(stream proximity)\nD = JRC depth-damage fraction, Asia residential (Huizinga et al. 2017): 0.5 m → 0.33, 1 m → 0.49, 2 m → 0.72, 6 m → 1.0"}</F>
            <p>Classes: ≥ 0.7 critical, 0.5–0.7 high, 0.3–0.5 moderate. A building in a landslide class 4–5 zone above the rain threshold is raised to at least high. The verification queue ranks buildings by risk × (1 − confidence) × people.</p>
          </section>

          <section id="routing">
            <h2>Evacuation routing</h2>
            <p>OpenStreetMap walking and driving networks are sampled every 30 m against the hourly depth and landslide grids. A road closes when water exceeds the walking (0.5 m) or vehicle (0.3 m) limit, when a bridge's river stage passes the cut level, when ≥ 20% of it lies in an active landslide class 5 zone, or when you block it.</p>
            <F>{"walk speed (Tobler 1993) = 6 · e^(−3.5·|tanθ + 0.05|) km/h, per 30 m segment\nassignment: min Σ people × time, subject to shelter capacity (network simplex, with an 'unplaced' overflow)"}</F>
            <p>Route ETAs are real travel times (crowding-slowed) plus the walk to the network; landslide and steep-slope penalties only steer route choice. Shelters are “reachable in this scenario” if dry, outside active landslide zones and connected. Capacity uses 3.5 m² per person (Sphere).</p>
          </section>

          <section id="forecast">
            <h2>Rain scenarios</h2>
            <ul>
              <li><b>Forecast</b>: the wettest hours of a chosen day from the Google Maps Platform Weather API (10 days); <b>Worst</b> multiplies it.</li>
              <li><b>Record</b>: the wettest day nearby in CHIRPS 2001–2024; its wettest H hours follow the IMD reduction formula <span className="mono">P_H = P_24 · (H/24)^(1/3)</span>.</li>
              <li><b>Custom</b>: a steady or early-peak storm you set.</li>
            </ul>
            <p>The 10-day strip screens each day with a one-reach model; run the full scenario for detail. The past 90 days come from NASA GPM IMERG.</p>
            <p><b>Upstream river flow</b> adds water that enters the area from outside (for example a CWC flood forecast for a main river): it is shared across reaches by their upstream area outside the box, so the main stem carries all of it.</p>
            <h3>Urban mode (water-logging screening)</h3>
            <F>{"filled = PriorityFlood+ε(FABDEM)   (Barnes et al. 2014)\nV_in = C_ws · Σ max(0, i − drain capacity) · A_ws   → fill each depression to the level that holds V_in"}</F>
            <p>Rain up to the storm-drain design capacity (25 mm/h, Mumbai's historical standard; configurable) is carried away; the rest ponds in depressions of the bare-earth terrain. People move when still water reaches 0.5 m (DEFRA/EA FD2321 hazard rating “danger for some”), or 0.3 m in fragile single-storey homes. Drains and culverts are ranked for pre-monsoon clearing by flow accumulation, ponding or flood susceptibility, and exposed people within 300 m; field photos marked blocked raise the priority. River overflow and tides are not modelled in urban mode.</p>
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
              <li><b>Ask Pravah</b> (ADK agent with tools) reads results and runs what-ifs through the same engines; it is told never to state a number it did not get from a tool.</li>
              <li><b>Advisory brief</b>: Gemini drafts recommendations from a compact facts sheet. A validator drops any recommendation that cites an unknown id or a number not in its cited facts, and fills empty horizons from deterministic rules; if Gemini fails, a rules-based brief is produced.</li>
              <li><b>Web incidents</b>: a separate agent with Google Search grounding returns sourced leads, shown with Google Search suggestions and labelled unverified.</li>
              <li><b>Field photos</b>: Gemini vision classifies structures or drains in photos your teams take; never Google Maps or Street View imagery.</li>
            </ul>
          </section>

          <section id="track">
            <h2>Track record: historical event replays</h2>
            <p className="body-m">The model is run with the observed rain (NASA IMERG, wettest 12 hours) of catalogued disasters. Only the rain trigger can be tested: the landslide records are located to within 5–10 km, and no observed flood extent exists inside these boxes. The last column shows how often the same monsoon crossed the 24-hour trigger on other days, i.e. how many false alarms a trigger-only warning would have raised.</p>
            <TrackRecord />
            <div className="notice warn"><Icon name="report" /><span><b>What this shows.</b> In Rudraprayag the Himalayan rain trigger (Dahal & Hasegawa 2008) was <b>not reached</b> for any of the three recorded events when fed satellite rain (0.36–0.95 of the threshold): IMERG's ~10 km cells smooth out cloudbursts, and the 2013 destruction came mostly from upstream flow, which the model takes only through the upstream-flow input. A forecast scenario that stays below the trigger therefore does not rule landslides out; plan with the record or IMD presets as well. In Mumbai the trigger was reached for both events, with 3–5 other days of the same monsoon also crossing the 24-hour threshold. Calibrating a satellite-rain trigger (for example a local rain percentile, as in NASA LHASA) is the next step.</span></div>
          </section>

          <section id="governance">
            <h2>Access and data governance</h2>
            <ul>
              <li><b>Sign-in and roles.</b> With sign-in enabled (Firebase Authentication with Google accounts), roles are viewer, field, analyst, approver and admin. Running scenarios and using Gemini need the analyst role; approving a brief needs the approver role; uploading field photos needs the field role.</li>
              <li><b>Sensitive outputs.</b> Building-level risk (the 3D buildings) is served only to signed-in users when sign-in is enabled, because labels like “critical risk” on individual houses can affect residents.</li>
              <li><b>Audit trail.</b> Brief generation, reviews, approvals, translations, official-status entries and area archiving are logged with the user, time and version.</li>
              <li><b>Where data lives.</b> Model inputs and outputs stay in this Google Cloud project (Cloud Storage, Firestore). Google Maps content is display only. Field photos are your teams' own and are used only to reclassify buildings and drains.</li>
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
