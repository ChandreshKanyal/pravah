// 3D water view: the 2D shallow-water flow model (backend engines/swe.py) animated over our own terrain (FABDEM bare
// earth, the same ground the model ran on), Sentinel-2 imagery, and Open Buildings coloured by the brief's risk.
// three.js scene in ../three/scene.ts. No Google 3D or Elevation content.
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { apiUrl, getAoiStatus, getRun } from "../api/client";
import { Button, Icon, IconButton, Segmented, Switch } from "../components/m3";
import FlowTimeline, { RATES, clockOf, span, type Rate } from "../three/FlowTimeline";
import { DEEP, HAZARD, RISK, SHALLOW, Scene3D, hazard, type Bld, type ColorMode, type Dem, type Frames, type Probe, type WaterStyle } from "../three/scene";
import type { RunResult } from "../types/api";
import "./view3d.css";

type Meta = {
  origin: [number, number]; bounds_m: [number, number, number, number]; aoi_m: [number, number][] | null; z_min: number; z_max: number;
  cell: number; width: number; height: number; mode: string; ground: { source: string; conditioned: boolean }; imagery: boolean;
};
type FlowMeta = {
  state: "none" | "queued" | "running" | "ready" | "failed" | "stale"; progress?: number; error?: string; model?: string;
  frame_s?: number; frames?: number; tail_h?: number; model_cell_m?: number; max_depth_m?: number; max_speed_ms?: number; flooded_km2?: number;
  hazard_km2?: Record<"low" | "some" | "most" | "all", number>; first_flooding_min?: number | null;
  compare_hand?: { hand_km2: number; flow_km2: number; both_km2: number; csi: number | null; share_of_hand_also_wet: number };
  stats?: { steps: number; wall_s: number; mass_balance_error: number; mean_dt_s: number }; ground?: { source: string; conditioned: boolean };
  sources?: { reach_id: number; q: number[]; outside_km2: number }[]; arf?: number; drain_mm_h?: number;
};
type Model = "flow" | "hand";

const COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];
const towards = (u: number, v: number) => COMPASS[Math.round(((Math.atan2(u, v) * 180) / Math.PI + 360) / 45) % 8];
const HZ_LABEL = ["Caution: shallow or slow water", "Danger for some (children, older people)", "Danger for most people", "Danger for everyone"];
const fmtDepth = (h: number) => (h >= 1 ? `${h.toFixed(1)} m` : `${Math.round(h * 100)} cm`);

/** Centre of the densest 600 m square of buildings (the main town), as metre offsets (x east, y north). */
function townCentre(b: Bld[]): [number, number] | null {
  if (!b.length) return null;
  const cnt = new Map<string, { n: number; x: number; y: number }>();
  for (const d of b) {
    const [x, y] = d.p[0];
    const k = `${Math.floor(x / 600)},${Math.floor(y / 600)}`;
    const v = cnt.get(k) ?? { n: 0, x: 0, y: 0 };
    v.n++; v.x += x; v.y += y; cnt.set(k, v);
  }
  let best = { n: 0, x: 0, y: 0 };
  cnt.forEach((v) => { if (v.n > best.n) best = v; });
  return [best.x / best.n, best.y / best.n];
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((res, rej) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => res(img);
    img.onerror = rej;
    img.src = url;
  });
}

export default function View3D() {
  const { aoiId = "" } = useParams();
  const [search] = useSearchParams();
  const runParam = search.get("run");
  const host = useRef<HTMLDivElement>(null);
  const sc = useRef<Scene3D | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [dem, setDem] = useState<Dem | null>(null);
  const [name, setName] = useState("");
  const [run, setRun] = useState<RunResult | null>(null);
  const [noRun, setNoRun] = useState(false);
  const [blds, setBlds] = useState<Bld[]>([]);
  const [risk, setRisk] = useState<Uint8Array | null>(null);
  const [flow, setFlow] = useState<FlowMeta | null>(null);
  const [model, setModel] = useState<Model | null>(null);
  const [frames, setFrames] = useState<Frames | null>(null);
  const [busy, setBusy] = useState("");
  const [imagery, setImagery] = useState(false);
  const [color, setColor] = useState<ColorMode>("depth");
  const [style, setStyle] = useState<WaterStyle>("real");
  const [lines, setLines] = useState(true);
  const [showB, setShowB] = useState(true);
  const [time, setTimeS] = useState(0);
  const [playing, setPlayingS] = useState(false);
  const [rate, setRateS] = useState<Rate>("normal");
  const [probe, setProbe] = useState<Probe | null>(null);
  const [err, setErr] = useState("");
  const played = useRef(new Set<string>());  // models already played from the start once
  const picked = useRef(false);               // the person chose a model: do not switch it for them
  const flown = useRef(false);
  const k = meta?.mode === "urban" ? 2 : 1.5;  // heights drawn k x so gentle slopes and water depth show (display only)

  // area, ground, latest run
  useEffect(() => {
    setErr("");
    fetch(apiUrl(`/api/aoi/${aoiId}/3d/meta`)).then((r) => (r.ok ? r.json() : Promise.reject())).then(setMeta).catch(() => setErr("3D data unavailable for this area"));
    fetch(apiUrl(`/api/aoi/${aoiId}/3d/dem.bin`)).then(async (r) => {
      if (!r.ok) throw new Error();
      const [w, h, cell] = (r.headers.get("X-Grid") ?? "0,0,30").split(",").map(Number);
      setDem({ w, h, cell, z: new Float32Array(await r.arrayBuffer()) });
    }).catch(() => setErr("Terrain unavailable"));
    getAoiStatus(aoiId).then((s) => {
      setName(s.name ?? "");
      const rid = runParam || s.latest_run_id;
      if (!rid) { setNoRun(true); return; }
      getRun(rid).then(setRun).catch(() => setNoRun(true));
    }).catch(() => undefined);
    // v: drop browser copies of an empty list cached before the OSM building fallback
    fetch(apiUrl(`/api/aoi/${aoiId}/3d/buildings.json?v=3`)).then((r) => r.json()).then(setBlds).catch(() => setBlds([]));
  }, [aoiId, runParam]);

  useEffect(() => {
    if (!run) return;
    fetch(apiUrl(`/api/runs/${run.run_id}/3d/risk.bin`)).then((r) => (r.ok ? r.arrayBuffer() : Promise.reject())).then((b) => setRisk(new Uint8Array(b))).catch(() => setRisk(null));
  }, [run]);

  // scene
  useEffect(() => {
    if (!host.current || !meta || !dem || sc.current) return;
    const s = new Scene3D(host.current);
    sc.current = s;
    if (import.meta.env.DEV) (window as any).__v3d = s;  // camera control for local screenshots
    s.setTerrain(dem, k);
    s.setOutline(meta.aoi_m);
    const span_ = Math.max(meta.bounds_m[2] - meta.bounds_m[0], meta.bounds_m[3] - meta.bounds_m[1]);
    s.flyTo(0, 0, span_ * 0.85, 48, -20, true);
    s.onTime = (t) => setTimeS(t);
    s.rate = RATES[rate];
    let alive = true, haveImagery = false;
    // shaded terrain first; it must never replace the satellite picture if that arrives sooner
    loadImage(apiUrl(`/api/aoi/${aoiId}/3d/base.jpg`)).then((img) => alive && !haveImagery && !s.isDisposed && s.setTexture(img)).catch(() => undefined);
    // satellite picture: made once per area (202 while Earth Engine prepares it)
    (async () => {
      for (let i = 0; i < 20 && alive; i++) {
        const r = await fetch(apiUrl(`/api/aoi/${aoiId}/3d/imagery.jpg`)).catch(() => null);
        if (r?.status === 200) {
          const url = URL.createObjectURL(await r.blob());
          const img = await loadImage(url).catch(() => null);
          if (img && alive) { haveImagery = true; s.setTexture(img); setImagery(true); }
          return;
        }
        if (!r || r.status !== 202) return;
        await new Promise((ok) => setTimeout(ok, 4000));
      }
    })();
    return () => { alive = false; s.dispose(); sc.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta, dem]);

  useEffect(() => { sc.current?.setBuildings(blds, risk); sc.current?.setBuildingsVisible(showB); }, [blds, risk, meta, dem]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { sc.current?.setBuildingsVisible(showB); }, [showB]);
  const town = useMemo(() => townCentre(blds), [blds]);
  useEffect(() => {
    if (!town || flown.current || !sc.current) return;
    flown.current = true;
    sc.current.flyTo(town[0], -town[1], meta?.mode === "urban" ? 2600 : 3200, 46);
  }, [town, meta, dem]);

  // flow model: start it if this run has none, follow progress, then show it
  useEffect(() => {
    if (!run) return;
    let alive = true, timer = 0;
    const poll = async () => {
      const r = await fetch(apiUrl(`/api/runs/${run.run_id}/flow`)).then((x) => x.json()).catch(() => null) as FlowMeta | null;
      if (!alive || !r) return;
      if (r.state === "none" || r.state === "stale") {
        const s = await fetch(apiUrl(`/api/runs/${run.run_id}/flow`), { method: "POST" }).then((x) => x.json()).catch(() => null);
        if (alive && s) setFlow(s);
      } else setFlow(r);
      if (r.state !== "ready" && r.state !== "failed") timer = window.setTimeout(poll, 3000);
    };
    poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [run]);
  useEffect(() => { if (flow && !model) setModel(flow.state === "ready" ? "flow" : "hand"); }, [flow, model]);
  useEffect(() => { if (flow?.state === "ready" && model === "hand" && !picked.current) setModel("flow"); }, [flow?.state]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!run || !model || !meta || (model === "flow" && flow?.state !== "ready")) return;
    let alive = true;
    setBusy(model === "flow" ? "Loading the water flow" : "Loading the map model");
    fetch(apiUrl(`/api/runs/${run.run_id}/flow/frames.bin?model=${model}`)).then(async (r) => {
      if (!r.ok) throw new Error(String(r.status));
      const data = new Uint8Array(await r.arrayBuffer());
      const n = Math.floor(data.length / (3 * meta.width * meta.height));
      if (!alive) return;
      setFrames({ n, w: meta.width, h: meta.height, frameS: model === "flow" ? flow?.frame_s ?? 300 : 3600, data, velocity: model === "flow" });
    }).catch(() => alive && setErr("Water frames unavailable")).finally(() => alive && setBusy(""));
    return () => { alive = false; };
  }, [run, model, model === "flow" ? flow?.state : null, meta]);  // eslint-disable-line react-hooks/exhaustive-deps

  // the flow model runs on after the rain stops (water from uphill still arrives); the hourly map covers the storm only
  const tailH = model === "flow" && frames?.velocity ? flow?.tail_h ?? 0 : 0;
  const duration = ((run?.rain_series_mm_h.length ?? 1) + tailH) * 3600;
  const rainShown = run ? [...run.rain_series_mm_h, ...new Array(tailH).fill(0)] : [];
  useEffect(() => {
    const s = sc.current;
    if (!s) return;
    s.duration = duration;
    s.setFrames(frames);
    const m = frames ? (frames.velocity ? "flow" : "hand") : "";
    if (frames && !played.current.has(m)) {  // first time for each model: watch the water rise from the start
      played.current.add(m);
      s.setTime(0); setTimeS(0); s.playing = true; setPlayingS(true);
    }
  }, [frames, duration]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { sc.current?.setStyle(style, color, lines); }, [style, color, lines, frames]);

  const setTime = (t: number) => { sc.current?.setTime(t); setTimeS(t); };
  const setPlaying = (p: boolean) => { if (sc.current) sc.current.playing = p; setPlayingS(p); };
  const setRate = (r: Rate) => { if (sc.current) sc.current.rate = RATES[r]; setRateS(r); };
  useEffect(() => { const s = sc.current; if (!s) return; const id = window.setInterval(() => { if (s.playing !== playing) setPlayingS(s.playing); }, 300); return () => clearInterval(id); }, [playing]);

  // click a spot: water there over time
  const down = useRef<[number, number] | null>(null);
  const onDown = (e: React.PointerEvent) => { down.current = [e.clientX, e.clientY]; };
  const onUp = (e: React.PointerEvent) => {
    const d = down.current;
    down.current = null;
    if (!d || Math.hypot(e.clientX - d[0], e.clientY - d[1]) > 5 || e.button !== 0) return;
    setProbe(sc.current?.pick(e.clientX, e.clientY) ?? null);
  };

  const flyWhole = () => {
    if (!meta || !sc.current) return;
    const a = meta.aoi_m;
    const cx = a ? (a[0][0] + a[2][0]) / 2 : 0, cy = a ? (a[0][1] + a[2][1]) / 2 : 0;
    const w = a ? Math.abs(a[2][0] - a[0][0]) : meta.bounds_m[2] - meta.bounds_m[0];
    sc.current.flyTo(cx, -cy, w * 1.25, 52);
  };

  const hz = flow?.hazard_km2;
  const ready = flow?.state === "ready";
  const running = flow && (flow.state === "queued" || flow.state === "running");

  return (
    <div className="doc-page v3d">
      <div ref={host} className="v3d-canvas" onPointerDown={onDown} onPointerUp={onUp} />
      <div className="card elevated v3d-panel">
        <div className="row nowrap"><Icon name="view_in_ar" style={{ color: "var(--primary)" }} /><span className="title-m grow">3D water · {name || "this area"}</span></div>
        {run && <span className="label-s muted">{run.rain_label}</span>}

        {running && (
          <div className="v3d-status">
            <span className="body-s">Simulating water flow… {Math.round(100 * (flow!.progress ?? 0))}%</span>
            <div className="lin"><i style={{ width: `${100 * (flow!.progress ?? 0)}%` }} /></div>
            <span className="body-s muted">Showing the map model hour by hour until it finishes (about 1–3 minutes).</span>
          </div>
        )}
        {flow?.state === "failed" && <div className="notice error"><Icon name="error" />Water flow simulation failed. Showing the map model.</div>}

        {frames && (
          <>
            <Segmented label="Water model" block value={model ?? "hand"} onChange={(m) => { picked.current = true; setModel(m); }}
              options={[{ value: "flow", label: "Water flow" }, { value: "hand", label: "Map (hourly)" }]} />
            <Segmented label="Colour water by" block value={color} onChange={setColor}
              options={[{ value: "depth", label: "Depth" }, { value: "hazard", label: "Danger" }]} />
            <Segmented label="Water drawn as" block value={style} onChange={setStyle}
              options={[{ value: "real", label: "Surface" }, { value: "cells", label: `Cells (${flow?.model_cell_m ?? meta?.cell ?? 30} m)` }]} />
          </>
        )}

        <ul className="v3d-legend">
          {frames && color === "depth" && <li><span className="ramp" style={{ background: `linear-gradient(90deg, ${SHALLOW}, ${DEEP})` }} /> Water depth: 3 cm → 3 m+</li>}
          {frames && color === "hazard" && <li className="label-m">Danger to people in the water</li>}
          {frames && color === "hazard" && [`linear-gradient(90deg, ${SHALLOW}, ${DEEP})`, ...HAZARD].map((c, i) => (
            <li key={c}><span className={i ? "sw" : "ramp short"} style={{ background: c }} /> {HZ_LABEL[i]}</li>
          ))}
          {frames?.velocity && lines && <li><span className="streak" /> Flow direction and speed</li>}
          <li><span className="bx" /> Simulated area</li>
          {showB && blds.length > 0 && (frames
            ? <li>{[...RISK].reverse().map((c, i) => <span key={i} className="sw" style={{ background: `rgb(${c.join(",")})` }} />)} Buildings by water against them now: dry → 15 cm → 50 cm → 1 m+</li>
            : <li>{RISK.map((c, i) => <span key={i} className="sw" style={{ background: `rgb(${c.join(",")})` }} />)} Building risk in the brief: critical → low</li>)}
        </ul>
        {frames && color === "hazard" && <p className="body-s muted">Flood hazard rating (DEFRA/EA FD2321): depth × (speed + 0.5), plus 0.5 above 25 cm for debris.</p>}

        {ready && model === "flow" && flow && (
          <dl className="v3d-stats">
            <div><dt>Deepest water</dt><dd className="num">{flow.max_depth_m} m</dd></div>
            <div><dt>Fastest flow</dt><dd className="num">{flow.max_speed_ms} m/s</dd></div>
            <div><dt>Water ≥ 5 cm</dt><dd className="num">{flow.flooded_km2} km²</dd></div>
            {hz && <div><dt>Dangerous to most</dt><dd className="num">{(hz.most + hz.all).toFixed(2)} km²</dd></div>}
            {flow.first_flooding_min != null && <div><dt>First flooding</dt><dd className="num">{flow.first_flooding_min} min</dd></div>}
          </dl>
        )}

        <div className="row" style={{ gap: 4 }}>
          <Button variant="tonal" size="small" icon="location_city" onClick={() => town && sc.current?.flyTo(town[0], -town[1], 1600, 42)} disabled={!town}>Town</Button>
          <Button variant="tonal" size="small" icon="crop_free" onClick={flyWhole}>Whole area</Button>
          <span className="spacer" />
          <IconButton icon={showB ? "domain_disabled" : "domain"} label={showB ? "Hide buildings" : "Show buildings"} onClick={() => setShowB(!showB)} />
        </div>

        {frames && (
          <details className="v3d-more">
            <summary className="label-l">Model details</summary>
            <div className="stack-s">
              {frames.velocity && <label className="row nowrap body-s" style={{ gap: 8 }}><Switch checked={lines} onChange={setLines} label="Flow lines" /> Flow lines</label>}
              {ready && flow && (
                <ul className="body-s muted v3d-facts">
                  <li>{flow.model}.</li>
                  <li>Ground: {flow.ground?.source}{flow.ground?.conditioned ? ", streams carved through false dams (narrow gorges, bridges)" : ""}.</li>
                  {flow.compare_hand && <li>The map (HAND) floods {flow.compare_hand.hand_km2} km²; {Math.round(100 * flow.compare_hand.share_of_hand_also_wet)}% of it also floods here. The flow model adds runoff in streams and gullies ({flow.compare_hand.flow_km2} km² with water ≥ 5 cm).</li>}
                  {flow.stats && <li>{flow.stats.steps.toLocaleString("en-IN")} time steps (mean {flow.stats.mean_dt_s} s), mass balance error {flow.stats.mass_balance_error.toExponential(0)}, {flow.stats.wall_s} s compute.</li>}
                  {flow.arf != null && flow.arf < 1 && <li>Rain reduced to {Math.round(100 * flow.arf)}% for the area (TP-29 areal reduction), as in the map model.</li>}
                  {!!flow.drain_mm_h && <li>Storm drains assumed to carry the first {flow.drain_mm_h} mm/h.</li>}
                  {flow.sources?.length ? <li>River inflow at {flow.sources.length} entry point(s): {flow.sources.map((s) => `${s.q[0]} m³/s`).join(", ")}.</li> : <li>No river inflow from outside the area in this scenario.</li>}
                </ul>
              )}
            </div>
          </details>
        )}

        {(busy || !dem) && !err && <div className="lin indet"><i /></div>}
        {busy && <span className="body-s muted">{busy}…</span>}
        {noRun && <div className="notice info"><Icon name="info" />No scenario yet: terrain and buildings only. Run a scenario on the Map tab to see the water.</div>}
        {err && <div className="notice error"><Icon name="error" />{err}</div>}
        <p className="body-s muted v3d-credit">Drag to move, right-drag to tilt and turn. Click a spot to see its water over time. Heights drawn {k}×.
          {imagery ? " Imagery: modified Copernicus Sentinel-2 data." : ""} Terrain: FABDEM. Buildings: Google Open Buildings.</p>
      </div>

      {probe && <ProbeCard probe={probe} scene={sc.current} frames={frames} time={time} start={run?.start_local} onClose={() => setProbe(null)} />}

      {run && frames && (
        <div className="v3d-time">
          <FlowTimeline duration={duration} time={time} setTime={setTime} playing={playing} setPlaying={setPlaying} rate={rate} setRate={setRate}
            rain={rainShown} start={run.start_local} windowHour={run.evac_window_h} />
        </div>
      )}
    </div>
  );
}

function ProbeCard({ probe, scene, frames, time, start, onClose }: {
  probe: Probe; scene: Scene3D | null; frames: Frames | null; time: number; start?: string | null; onClose: () => void;
}) {
  if (!scene || !frames) return null;
  const i = probe.r * frames.w + probe.c;
  const [h, u, v] = scene.sample(i);
  const sp = Math.hypot(u, v);
  const ser = scene.series(i);
  const peak = Math.max(0, ...ser);
  const kPeak = ser.indexOf(peak);
  const kArr = ser.findIndex((x) => x >= 0.05);
  const at = (k: number) => clockOf(start, k * frames.frameS) ?? span(k * frames.frameS);
  const W = 220, H = 56, ymax = Math.max(0.3, peak * 1.1);
  const pts = ser.map((x, k) => `${(k / Math.max(1, ser.length - 1)) * W},${H - (x / ymax) * H}`).join(" ");
  const nowX = (Math.min(time / frames.frameS, ser.length - 1) / Math.max(1, ser.length - 1)) * W;
  const hr = hazard(h, sp);
  return (
    <div className="card elevated v3d-probe" role="dialog" aria-label="Water at this spot">
      <div className="row nowrap"><Icon name="water_drop" className="sm" style={{ color: "var(--primary)" }} /><span className="title-s grow">Water at this spot</span>
        <IconButton icon="close" label="Close" small onClick={onClose} /></div>
      <p className="body-m">{h >= 0.03 ? <>Now <b>{fmtDepth(h)}</b> deep{frames.velocity && sp >= 0.05 ? <>, flowing <b>{sp.toFixed(1)} m/s</b> towards the {towards(u, v)}</> : ""}.</> : "Dry now."}
        {frames.velocity && h >= 0.05 && <> {HZ_LABEL[hr < 0.75 ? 0 : hr < 1.25 ? 1 : hr < 2 ? 2 : 3]}.</>}</p>
      <svg width={W} height={H} className="v3d-spark" role="img" aria-label="Depth over the storm">
        <polyline points={`0,${H} ${pts} ${W},${H}`} className="area" />
        <polyline points={pts} className="line" />
        <line x1={nowX} x2={nowX} y1={0} y2={H} className="now" />
      </svg>
      <p className="body-s muted">{kArr >= 0 ? `Water arrives (5 cm) at ${at(kArr)}; peaks at ${fmtDepth(peak)} at ${at(kPeak)}.` : "No flooding here in this scenario."}
        {" "}Ground {Math.round(probe.ground)} m above sea level.</p>
      {probe.building && <p className="body-s">Building, about {probe.building.h} m tall.</p>}
    </div>
  );
}
