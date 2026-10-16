import { useState } from "react";
import { COLORS } from "../layers/factories";
import type { LayerKey } from "./LayerPanel";
import { Icon } from "./m3";

type Sym = { kind: "line" | "dot" | "ramp" | "box"; color: string | string[]; label: string; thick?: boolean };
const rgb = (c: readonly number[]) => `rgb(${c[0]},${c[1]},${c[2]})`;
const DEPTH = ["var(--depth-1)", "var(--depth-2)", "var(--depth-3)", "var(--depth-4)", "var(--depth-5)"];
const SUS = ["var(--sus-1)", "var(--sus-2)", "var(--sus-3)", "var(--sus-4)", "var(--sus-5)"];

/** Compact map key (Google Maps style): only what is currently drawn, colours taken from the layer factories. */
export default function MapLegend({ on, hasRun, blocked }: { on: Set<LayerKey>; hasRun: boolean; blocked: boolean }) {
  const [open, setOpen] = useState(true);
  const items: Sym[] = [{ kind: "box", color: "#ffffff", label: "Simulated area" }];
  if (hasRun && on.has("depth")) items.push({ kind: "ramp", color: DEPTH, label: "Flood depth 5 cm → 3 m+" });
  if (hasRun && on.has("ponding")) items.push({ kind: "ramp", color: ["#9ecae1", "#3182bd", "#08306b"], label: "Ponding low → high" });
  if (hasRun && on.has("lsi")) items.push({ kind: "ramp", color: SUS, label: "Landslide risk low → high" });
  if (on.has("fsi")) items.push({ kind: "ramp", color: SUS, label: "Flood susceptibility" });
  if (on.has("lsi_static")) items.push({ kind: "ramp", color: SUS, label: "Landslide susceptibility" });
  if (hasRun && on.has("roads")) items.push(
    { kind: "line", color: rgb(COLORS.open), label: "Road open" },
    { kind: "line", color: rgb(COLORS.closesLater), label: "Road closes later" },
    { kind: "line", color: rgb(COLORS.closed), label: "Road closed now (thick)", thick: true });
  if (hasRun && on.has("routes")) items.push({ kind: "line", color: rgb(COLORS.route), label: "Evacuation route", thick: true });
  if (hasRun && on.has("bridges")) items.push({ kind: "dot", color: [rgb(COLORS.open), rgb(COLORS.closesLater), rgb(COLORS.closed)], label: "Bridge open · later · closed" });
  if (on.has("shelters")) items.push({ kind: "dot", color: rgb(COLORS.shelter), label: hasRun ? "Shelter in use (S#), bigger = fuller" : "Candidate shelter (S#)" });
  if (on.has("all_shelters")) items.push({ kind: "dot", color: rgb(COLORS.shelterOff), label: "Candidate shelter, not used" });
  if (hasRun && on.has("assembly")) items.push({ kind: "dot", color: rgb(COLORS.assembly), label: "Assembly point (A#)" });
  if (on.has("medical")) items.push({ kind: "dot", color: rgb(COLORS.medical), label: "Hospital / clinic (+)" });
  if (hasRun && on.has("medical")) items.push({ kind: "dot", color: rgb(COLORS.staging), label: "Staging point (G#)" });
  if (hasRun && on.has("drains")) items.push({ kind: "dot", color: rgb(COLORS.drain), label: "Drain to inspect (D#)" });
  if (on.has("streams")) items.push({ kind: "dot", color: "#ffffff", label: "Flow hotspot" });
  if (on.has("crowd")) items.push({ kind: "dot", color: rgb(COLORS.crowd), label: "Crowding hotspot" });
  if (on.has("history")) items.push({ kind: "dot", color: ["#bd0026", "#fbbc04"], label: "Past landslide · web report" });
  if (blocked) items.push({ kind: "box", color: "#d7191c", label: "Blocked road (yours)" });

  return (
    <div className={`map-legend ${open ? "open" : ""}`}>
      <button className="lg-head sl" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Icon name="legend_toggle" className="sm" /> Legend <Icon name={open ? "expand_less" : "expand_more"} className="sm" />
      </button>
      {open && <ul>{items.map((s) => (
        <li key={s.label}>
          <span className="sym">{s.kind === "ramp" ? <span className="ramp">{(s.color as string[]).map((c) => <i key={c} style={{ background: c }} />)}</span>
            : s.kind === "line" ? <span className="ln" style={{ background: s.color as string, height: s.thick ? 5 : 3 }} />
            : s.kind === "box" ? <span className="bx" style={{ borderColor: s.color as string }} />
            : ([] as string[]).concat(s.color).map((c) => <span key={c} className="dt" style={{ background: c }} />)}</span>
          {s.label}
        </li>))}</ul>}
    </div>
  );
}
