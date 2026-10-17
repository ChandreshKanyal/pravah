import { useState } from "react";
import { COLORS, LINES, RAMPS, css, markerUrl, rasterAlpha, type LineStyle, type Marker } from "../layers/factories";
import { Icon } from "./m3";

/** Every symbol the workspace map can draw. The map key and the layer panel render these, so a swatch always matches
 *  the drawing (colour, line or marker shape, dash, width, edge and strength). */
export type SymKey =
  | "area" | "depth" | "water" | "ponding" | "fsi" | "hand" | "crowdShade" | "stream" | "hotspot"
  | "roadOpen" | "roadLater" | "roadClosed" | "roadCut" | "route" | "routeClosed" | "bridgeLater" | "bridgeClosed" | "blocked" | "traffic"
  | "shelter" | "userShelter" | "candidate" | "assembly" | "staging" | "medical" | "drain" | "crowd" | "webReport" | "fix";

type SymDef = { label: string; sub?: string } & (
  | { kind: "ramp"; colors: string[]; alpha: number }
  | { kind: "line"; style: LineStyle }
  | { kind: "icon"; marker: Marker }
  | { kind: "area" }
  | { kind: "fill"; color: string; edge: string }
);

export const SYMS: Record<SymKey, SymDef> = {
  area: { kind: "area", label: "Simulated area" },
  depth: { kind: "ramp", colors: RAMPS.depth, alpha: rasterAlpha("depth"), label: "Deepest flood so far", sub: "5 cm → 3 m+ · see 3D for water draining away" },
  water: { kind: "fill", color: css(COLORS.water, rasterAlpha("depth")), edge: "transparent", label: "River or lake, normal level" },
  ponding: { kind: "ramp", colors: RAMPS.ponding, alpha: rasterAlpha("ponding"), label: "Ponding likelihood", sub: "low → high" },
  fsi: { kind: "ramp", colors: RAMPS.sus, alpha: rasterAlpha("fsi"), label: "Flood susceptibility", sub: "very low → very high" },
  hand: { kind: "ramp", colors: RAMPS.hand, alpha: rasterAlpha("hand"), label: "Height above stream", sub: "0 → 20 m" },
  crowdShade: { kind: "ramp", colors: RAMPS.crowd, alpha: rasterAlpha("crowd"), label: "Crowding", sub: "low → high" },
  stream: { kind: "line", style: { ...LINES.stream, color: [...COLORS.stream.slice(0, 3), Math.round(255 * rasterAlpha("streams"))] as LineStyle["color"] }, label: "Stream" },
  hotspot: { kind: "icon", marker: "hotspot", label: "Flow hotspot" },
  roadOpen: { kind: "line", style: LINES.roadOpen, label: "Road open" },
  roadLater: { kind: "line", style: LINES.roadLater, label: "Road closes later" },
  roadClosed: { kind: "line", style: LINES.roadClosed, label: "Road closed", sub: "where the flooding is" },
  roadCut: { kind: "line", style: LINES.roadCut, label: "No through road", sub: "blocked further along" },
  route: { kind: "line", style: LINES.route, label: "Evacuation route", sub: "wider = more people" },
  routeClosed: { kind: "line", style: LINES.routeClosed, label: "Route closed", sub: "a road on it has closed" },
  bridgeLater: { kind: "icon", marker: "bridgeLater", label: "Bridge closes later" },
  bridgeClosed: { kind: "icon", marker: "bridgeClosed", label: "Bridge closed" },
  blocked: { kind: "fill", color: css(COLORS.blocked, 60 / 255), edge: css(COLORS.blocked), label: "Area you blocked" },
  traffic: { kind: "ramp", colors: RAMPS.traffic, alpha: 1, label: "Live traffic (Google)", sub: "fast → slow" },
  shelter: { kind: "icon", marker: "shelter", label: "Shelter in use (S#)", sub: "bigger = fuller" },
  userShelter: { kind: "icon", marker: "shelter", label: "Shelter you added", sub: "used from the next run" },
  candidate: { kind: "icon", marker: "candidate", label: "Candidate shelter, not used" },
  assembly: { kind: "icon", marker: "assembly", label: "Assembly point (A#)" },
  staging: { kind: "icon", marker: "staging", label: "Staging point (G#)" },
  medical: { kind: "icon", marker: "medical", label: "Hospital or clinic" },
  fix: { kind: "icon", marker: "fix", label: "Fix before the rain", sub: "number = priority" },
  drain: { kind: "icon", marker: "drain", label: "Drain to inspect (D#)" },
  crowd: { kind: "icon", marker: "crowd", label: "Crowding hotspot (X#)" },
  webReport: { kind: "icon", marker: "webReport", label: "Web report (year)" },
};
const ORDER = Object.keys(SYMS) as SymKey[];

/** One swatch, drawn the way the map draws it. */
export function Sym({ k, small }: { k: SymKey; small?: boolean }) {
  const s = SYMS[k];
  if (s.kind === "ramp") return <span className="ramp" style={{ opacity: s.alpha }}>{s.colors.map((c) => <i key={c} style={{ background: c }} />)}</span>;
  if (s.kind === "icon") return <img className="mk" src={markerUrl(s.marker)} alt="" width={small ? 14 : 16} height={small ? 14 : 16} />;
  if (s.kind === "fill") return <span className="fl" style={{ background: s.color, borderColor: s.edge }} />;
  if (s.kind === "area") {
    return <svg className="ln" width="22" height="14" viewBox="0 0 22 14" aria-hidden="true">
      <rect x="2" y="2" width="18" height="10" rx="1" fill="none" stroke="#202124" strokeOpacity=".82" strokeWidth="3.5" />
      <rect x="2" y="2" width="18" height="10" rx="1" fill="none" stroke="#fff" strokeWidth="1.75" strokeDasharray="3.5 2.6" /></svg>;
  }
  const { color, width, casing, dash } = s.style;
  const w = small ? 24 : 28;
  return (
    <svg className={`ln ${k === "stream" ? "halo" : ""}`} width={w} height="12" viewBox={`0 0 ${w} 12`} aria-hidden="true">
      {casing && <line x1="2" y1="6" x2={w - 2} y2="6" stroke={css(COLORS.casing)} strokeWidth={casing} strokeLinecap="round" />}
      <line x1="2" y1="6" x2={w - 2} y2="6" stroke={css(color)} strokeWidth={width} strokeLinecap={dash ? "butt" : "round"}
        strokeDasharray={dash ? `${dash[0] * width} ${dash[1] * width}` : undefined} />
    </svg>
  );
}

const readOpen = () => {
  try { const v = localStorage.getItem("pravah-legend"); if (v) return v === "open"; } catch { /* storage blocked */ }
  return typeof window === "undefined" || window.innerWidth > 640;
};

/** Compact map key (Google Maps style): only symbols that are on the map right now (`drawn` counts what the layers drew,
 *  so road, bridge and route states follow the selected hour), in the same order as the layer panel. */
export default function MapLegend({ drawn, when, hasRun }: { drawn: Partial<Record<SymKey, number>>; when?: string; hasRun: boolean }) {
  const [open, setOpen] = useState(readOpen);
  const toggle = () => { setOpen(!open); try { localStorage.setItem("pravah-legend", open ? "closed" : "open"); } catch { /* storage blocked */ } };
  const keys = ORDER.filter((k) => (drawn[k] ?? 0) > 0);
  const label = (k: SymKey) => (k === "candidate" && !hasRun ? "Candidate shelter (S#)" : SYMS[k].label);
  return (
    <div className={`map-legend ${open ? "open" : ""}`}>
      <button className="lg-head sl" onClick={toggle} aria-expanded={open}>
        <Icon name="legend_toggle" className="sm" /> Legend {when && <span className="lg-when">{when}</span>}
        <Icon name={open ? "expand_less" : "expand_more"} className="sm" />
      </button>
      {open && <ul>{keys.map((k) => (
        <li key={k}><span className="sym"><Sym k={k} /></span>
          <span>{label(k)}{SYMS[k].sub && <span className="lg-sub">{SYMS[k].sub}</span>}</span></li>))}</ul>}
    </div>
  );
}
