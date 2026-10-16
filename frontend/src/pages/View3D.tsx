// S19 3D view (option B): our own Copernicus DEM meshed as terrain, the run's flood depth draped per hour, and Open
// Buildings extruded by height and coloured by estimated risk. Standalone deck.gl, no Google 3D or Elevation content.
// Terrain and buildings share UTM metre offsets from the grid centre, so they align exactly.
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { COORDINATE_SYSTEM, Deck } from "@deck.gl/core";
import { PathLayer, PolygonLayer } from "@deck.gl/layers";
import { SimpleMeshLayer } from "@deck.gl/mesh-layers";
import { apiUrl, getAoiStatus, getRun } from "../api/client";
import { Button, Icon, IconButton, Segmented } from "../components/m3";
import TimeSlider from "../components/TimeSlider";
import type { RunResult } from "../types/api";

type Meta = { origin: [number, number]; bounds_m: [number, number, number, number]; aoi_m: [number, number][] | null; z_min: number; z_max: number; cell: number };
type Bld = { p: [number, number][]; z: number; h: number; r: number };
type Dem = { w: number; h: number; cell: number; z: Float32Array };
const RISK: [number, number, number][] = [[217, 48, 37], [242, 153, 0], [251, 188, 4], [232, 234, 237]];

/** Grid mesh: positions in metre offsets (x east, y north, z up), normals from central differences, UVs 0..1. */
function buildMesh(d: Dem, k: number) {
  const { w, h, cell, z } = d;
  const pos = new Float32Array(w * h * 3), nor = new Float32Array(w * h * 3), uv = new Float32Array(w * h * 2);
  const W = w * cell, H = h * cell;
  for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) {
    const i = r * w + c;
    pos[3 * i] = -W / 2 + (c + 0.5) * cell; pos[3 * i + 1] = H / 2 - (r + 0.5) * cell; pos[3 * i + 2] = z[i] * k;
    const zx = (z[r * w + Math.min(c + 1, w - 1)] - z[r * w + Math.max(c - 1, 0)]) * k / (2 * cell);
    const zy = (z[Math.max(r - 1, 0) * w + c] - z[Math.min(r + 1, h - 1) * w + c]) * k / (2 * cell);
    const n = Math.hypot(zx, zy, 1);
    nor[3 * i] = -zx / n; nor[3 * i + 1] = -zy / n; nor[3 * i + 2] = 1 / n;
    uv[2 * i] = (c + 0.5) / w; uv[2 * i + 1] = (r + 0.5) / h;
  }
  const idx = new Uint32Array((w - 1) * (h - 1) * 6);
  let j = 0;
  for (let r = 0; r < h - 1; r++) for (let c = 0; c < w - 1; c++) {
    const a = r * w + c, b = a + 1, e = a + w, f = e + 1;
    idx.set([a, e, b, b, e, f], j); j += 6;
  }
  return { attributes: { positions: { value: pos, size: 3 }, normals: { value: nor, size: 3 }, texCoords: { value: uv, size: 2 } }, indices: { value: idx, size: 1 } };
}

/** Ground height (m) at metre offset (x, y) from the nearest DEM mesh cell. */
function demAt(d: Dem, x: number, y: number) {
  const c = Math.min(d.w - 1, Math.max(0, Math.floor((x + (d.w * d.cell) / 2) / d.cell)));
  const r = Math.min(d.h - 1, Math.max(0, Math.floor(((d.h * d.cell) / 2 - y) / d.cell)));
  return d.z[r * d.w + c];
}

/** Metre offset -> lon/lat near the origin (equirectangular, fine within a 20 km box). */
function offsetToLonLat(o: [number, number], x: number, y: number): [number, number] {
  return [o[0] + x / (111320 * Math.cos((o[1] * Math.PI) / 180)), o[1] + y / 110540];
}

/** Centre of the densest 600 m square of buildings (the main town), as a metre offset. */
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

const DEPTH = ["#c6dbef", "#9ecae1", "#6baed6", "#3182bd", "#08519c"];

export default function View3D() {
  const { aoiId = "" } = useParams();
  const ref = useRef<HTMLDivElement>(null);
  const deck = useRef<Deck | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [dem, setDem] = useState<Dem | null>(null);
  const [run, setRun] = useState<RunResult | null>(null);
  const [blds, setBlds] = useState<Bld[]>([]);
  const [hour, setHour] = useState(1);
  const [ex, setEx] = useState<"1" | "1.5" | "2">("1.5");
  const [showB, setShowB] = useState(true);
  const [err, setErr] = useState("");
  const [name, setName] = useState("");
  const [noRun, setNoRun] = useState(false);
  const [tex, setTex] = useState<HTMLImageElement | null>(null);
  const [texBusy, setTexBusy] = useState(false);
  const flown = useRef(false);

  useEffect(() => {
    fetch(apiUrl(`/api/aoi/${aoiId}/3d/meta`)).then((r) => r.json()).then(setMeta).catch(() => setErr("3D data unavailable for this area"));
    fetch(apiUrl(`/api/aoi/${aoiId}/3d/dem.bin?step=2`)).then(async (r) => {
      const [w, h, cell] = (r.headers.get("X-Grid") ?? "0,0,60").split(",").map(Number);
      setDem({ w, h, cell, z: new Float32Array(await r.arrayBuffer()) });
    }).catch(() => setErr("Terrain unavailable"));
    getAoiStatus(aoiId).then((s) => { setName(s.name ?? ""); if (!s.latest_run_id) setNoRun(true); if (s.latest_run_id) getRun(s.latest_run_id).then((r) => { setRun(r); setHour(r.rain_series_mm_h.length); }); }).catch(() => undefined);
  }, [aoiId]);
  useEffect(() => {
    if (!run && !noRun) return;
    fetch(apiUrl(run ? `/api/runs/${run.run_id}/3d/buildings.json?aoi_id=${aoiId}` : `/api/aoi/${aoiId}/3d/buildings.json`)).then((r) => r.json()).then(setBlds).catch(() => setBlds([]));
  }, [run, noRun, aoiId]);

  useEffect(() => {
    if (!ref.current || !meta || deck.current) return;
    deck.current = new Deck({
      parent: ref.current,
      initialViewState: { longitude: meta.origin[0], latitude: meta.origin[1], zoom: 13.7, pitch: 60, bearing: -20, maxPitch: 85 },
      controller: true,
      layers: [],
      getTooltip: ({ object }: any) => (object && object.h ? { text: `Building · ${["critical", "high", "moderate", "low"][object.r]} estimated risk · ${object.h} m tall` } : null),
    });
    return () => { deck.current?.finalize(); deck.current = null; };
  }, [meta]);

  // Load the hourly texture as an <img> ourselves (Safari fails deck's ImageBitmap path); keep the old one until ready.
  useEffect(() => {
    if (!run && !noRun) return;
    const img = new Image();
    img.crossOrigin = "anonymous";
    setTexBusy(true);
    img.onload = () => { setTex(img); setTexBusy(false); };
    img.onerror = () => setTexBusy(false);
    img.src = apiUrl(run ? `/api/runs/${run.run_id}/3d/texture_h${hour}.jpg?aoi_id=${aoiId}` : `/api/aoi/${aoiId}/3d/base.jpg`);
    return () => { img.onload = null; img.onerror = null; };
  }, [run, noRun, hour, aoiId]);

  const view = (x: number, y: number, zoom: number, pitch = 62) => {
    if (!meta || !deck.current) return;
    const [longitude, latitude] = offsetToLonLat(meta.origin, x, y);
    deck.current.setProps({ initialViewState: { longitude, latitude, zoom, pitch, bearing: -20, maxPitch: 85, transitionDuration: 900 } as any });
  };
  const town = useMemo(() => townCentre(blds), [blds]);
  useEffect(() => { if (town && !flown.current && deck.current) { flown.current = true; view(town[0], town[1], 15.4); } });

  const k = Number(ex);
  const mesh = useMemo(() => (dem ? buildMesh(dem, k) : null), [dem, k]);
  const layers = useMemo(() => {
    if (!meta || !mesh) return [];
    const common = { coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS, coordinateOrigin: [meta.origin[0], meta.origin[1], 0] as [number, number, number] };
    const L: any[] = [new SimpleMeshLayer({
      id: `terrain-${k}`, ...common, data: [0], mesh: mesh as any, texture: (tex ?? null) as any, getPosition: () => [0, 0, 0],
      getColor: [178, 190, 160, 255], material: { ambient: 0.6, diffuse: 0.55, shininess: 4, specularColor: [20, 20, 20] },
    })];
    if (meta.aoi_m && dem) {
      // simulated-area outline draped on the terrain, densified every cell so it follows the ground
      const pts: [number, number, number][] = [];
      for (let i = 0; i < meta.aoi_m.length - 1; i++) {
        const [x0, y0] = meta.aoi_m[i], [x1, y1] = meta.aoi_m[i + 1];
        const n = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0) / dem.cell));
        for (let j = 0; j < n; j++) { const x = x0 + ((x1 - x0) * j) / n, y = y0 + ((y1 - y0) * j) / n; pts.push([x, y, demAt(dem, x, y) * k + 12]); }
      }
      pts.push(pts[0]);
      L.push(new PathLayer({ id: `aoi-${k}`, ...common, data: [{ p: pts }], getPath: (d: any) => d.p, getColor: [217, 48, 37, 255], getWidth: 4,
        widthUnits: "pixels", jointRounded: true, parameters: { depthCompare: "always" } as any }));
    }
    if (showB && blds.length) {
      L.push(new PolygonLayer<Bld>({
        id: "buildings", ...common, data: blds, extruded: true, pickable: true,
        getPolygon: (d) => d.p.map(([x, y]) => [x, y, d.z * k]), getElevation: (d) => d.h * k,
        getFillColor: (d) => [...RISK[d.r], 255] as any, material: { ambient: 0.55, diffuse: 0.6 }, updateTriggers: { getPolygon: k, getElevation: k },
      }));
    }
    return L;
  }, [meta, mesh, tex, dem, k, blds, showB]);

  useEffect(() => { deck.current?.setProps({ layers }); }, [layers]);

  return (
    <div className="doc-page" style={{ background: "linear-gradient(180deg, #bcd4f0 0%, #e8eff7 55%, #dfe5ec 100%)", overflow: "hidden" }}>
      <div ref={ref} style={{ position: "absolute", inset: 0 }} />
      <div className="card elevated stack-s v3d-panel">
        <div className="row nowrap"><Icon name="view_in_ar" style={{ color: "var(--primary)" }} /><span className="title-m grow">3D · {name || "this area"}</span></div>
        <p className="body-s muted">The simulated area and its surroundings: our terrain model with rivers and flood water at the selected hour, and buildings coloured by estimated risk. Right-drag to tilt and rotate.</p>
        {run && <span className="label-s muted">{run.rain_label}</span>}
        <ul className="v3d-legend">
          <li><span className="bx" /> Simulated area</li>
          <li><span className="sw" style={{ background: "rgb(66,133,214)" }} /> River / main stream</li>
          <li><span className="ramp">{DEPTH.map((c) => <i key={c} style={{ background: c }} />)}</span> Flood 5 cm → 3 m+</li>
          <li>{(["critical", "high", "moderate", "low"] as const).map((r, i) => <span key={r} className="sw" title={r} style={{ background: `rgb(${RISK[i].join(",")})` }} />)} Building risk: critical → low</li>
        </ul>
        <Segmented label="Height exaggeration" block value={ex} onChange={setEx} options={[{ value: "1", label: "1×" }, { value: "1.5", label: "1.5×" }, { value: "2", label: "2×" }]} />
        <div className="row" style={{ gap: 4 }}>
          <Button variant="tonal" size="small" icon="location_city" onClick={() => town && view(town[0], town[1], 15.4)} disabled={!town}>Town</Button>
          <Button variant="tonal" size="small" icon="crop_free" onClick={() => view(0, 600, 12.35, 45)}>Whole area</Button>
          <span className="spacer" />
          <IconButton icon={showB ? "domain_disabled" : "domain"} label={showB ? "Hide buildings" : "Show buildings"} onClick={() => setShowB(!showB)} />
        </div>
        {(!dem || texBusy) && !err && <div className="lin indet"><i /></div>}
        {!run && <div className="notice info"><Icon name="info" />No scenario yet: terrain, rivers and buildings only. Run a scenario on the Map tab to see flood water and building risk.</div>}
        {err && <div className="notice error"><Icon name="error" />{err}</div>}
      </div>
      {run && (
        <div style={{ position: "absolute", left: 16, right: 16, bottom: 24, zIndex: 5, display: "flex" }}>
          <TimeSlider hours={run.rain_series_mm_h.length} hour={hour} setHour={setHour} rain={run.rain_series_mm_h} />
        </div>
      )}
    </div>
  );
}
