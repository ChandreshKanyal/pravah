// S19 3D view (option B): our own Copernicus DEM meshed as terrain, the run's flood depth draped per hour, and Open
// Buildings extruded by height and coloured by estimated risk. Standalone deck.gl, no Google 3D or Elevation content.
// Terrain and buildings share UTM metre offsets from the grid centre, so they align exactly.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { COORDINATE_SYSTEM, Deck } from "@deck.gl/core";
import { PolygonLayer } from "@deck.gl/layers";
import { SimpleMeshLayer } from "@deck.gl/mesh-layers";
import { apiUrl, getAoiStatus, getRun } from "../api/client";
import { Button, Icon, Segmented } from "../components/m3";
import TimeSlider from "../components/TimeSlider";
import type { RunResult } from "../types/api";

type Meta = { origin: [number, number]; bounds_m: [number, number, number, number]; z_min: number; z_max: number; cell: number };
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

  useEffect(() => {
    fetch(apiUrl(`/api/aoi/${aoiId}/3d/meta`)).then((r) => r.json()).then(setMeta).catch(() => setErr("3D data unavailable for this area"));
    fetch(apiUrl(`/api/aoi/${aoiId}/3d/dem.bin?step=2`)).then(async (r) => {
      const [w, h, cell] = (r.headers.get("X-Grid") ?? "0,0,60").split(",").map(Number);
      setDem({ w, h, cell, z: new Float32Array(await r.arrayBuffer()) });
    }).catch(() => setErr("Terrain unavailable"));
    getAoiStatus(aoiId).then((s) => { if (s.latest_run_id) getRun(s.latest_run_id).then((r) => { setRun(r); setHour(r.rain_series_mm_h.length); }); }).catch(() => undefined);
  }, [aoiId]);
  useEffect(() => {
    if (!run) return;
    fetch(apiUrl(`/api/runs/${run.run_id}/3d/buildings.json?aoi_id=${aoiId}`)).then((r) => r.json()).then(setBlds).catch(() => setBlds([]));
  }, [run, aoiId]);

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

  const k = Number(ex);
  const mesh = useMemo(() => (dem ? buildMesh(dem, k) : null), [dem, k]);
  const layers = useMemo(() => {
    if (!meta || !mesh) return [];
    const common = { coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS, coordinateOrigin: [meta.origin[0], meta.origin[1], 0] as [number, number, number] };
    const tex = run ? apiUrl(`/api/runs/${run.run_id}/3d/texture_h${hour}.png?aoi_id=${aoiId}`) : null;
    const L: any[] = [new SimpleMeshLayer({
      id: `terrain-${k}`, ...common, data: [0], mesh: mesh as any, texture: tex as any, getPosition: () => [0, 0, 0],
      getColor: [178, 190, 160, 255], material: { ambient: 0.6, diffuse: 0.55, shininess: 4, specularColor: [20, 20, 20] },
    })];
    if (showB && blds.length) {
      L.push(new PolygonLayer<Bld>({
        id: "buildings", ...common, data: blds, extruded: true, pickable: true,
        getPolygon: (d) => d.p.map(([x, y]) => [x, y, d.z * k]), getElevation: (d) => d.h * k,
        getFillColor: (d) => [...RISK[d.r], 255] as any, material: { ambient: 0.55, diffuse: 0.6 }, updateTriggers: { getPolygon: k, getElevation: k },
      }));
    }
    return L;
  }, [meta, mesh, run, hour, k, blds, showB, aoiId]);

  useEffect(() => { deck.current?.setProps({ layers }); }, [layers]);

  return (
    <div className="doc-page" style={{ background: "linear-gradient(180deg, #bcd4f0 0%, #e8eff7 55%, #dfe5ec 100%)", overflow: "hidden" }}>
      <div ref={ref} style={{ position: "absolute", inset: 0 }} />
      <div className="card elevated stack-s" style={{ position: "absolute", top: 16, left: 16, width: 340, zIndex: 5 }}>
        <div className="row nowrap"><Icon name="view_in_ar" className="lg" style={{ color: "var(--primary)" }} /><span className="title-l grow">3D view</span></div>
        <p className="body-s muted">Terrain from Copernicus DEM, flood depth from the latest run, buildings from Google Open Buildings coloured by estimated risk. Drag to pan, right-drag or Ctrl-drag to tilt and rotate.</p>
        {run && <span className="label-m muted">{run.rain_label}</span>}
        <Segmented label="Vertical exaggeration" block value={ex} onChange={setEx} options={[{ value: "1", label: "1×" }, { value: "1.5", label: "1.5×" }, { value: "2", label: "2×" }]} />
        <div className="row">
          {(["critical", "high", "moderate", "low"] as const).map((r, i) => (
            <span key={r} className="row nowrap body-s" style={{ gap: 4 }}><i style={{ width: 12, height: 12, borderRadius: 3, background: `rgb(${RISK[i].join(",")})`, display: "inline-block", border: "1px solid #0002" }} />{r}</span>
          ))}
        </div>
        <div className="row">
          <Button variant="text" size="small" icon={showB ? "visibility_off" : "visibility"} onClick={() => setShowB(!showB)}>{showB ? "Hide" : "Show"} buildings</Button>
          <span className="spacer" />
          <Link to={`/area/${aoiId}`} className="btn btn-tonal small sl"><Icon name="map" /> Map</Link>
        </div>
        {!dem && !err && <div className="lin indet"><i /></div>}
        {!run && <div className="notice info"><Icon name="info" />Run a scenario to see flood water and building risk.</div>}
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
