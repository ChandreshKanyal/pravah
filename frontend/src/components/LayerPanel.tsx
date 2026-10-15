import { useEffect, useRef, useState } from "react";
import type { MapType } from "./MapCanvas";
import { Icon, IconButton, Switch } from "./m3";

export type LayerKey =
  | "depth" | "lsi" | "fsi" | "lsi_static" | "hand" | "streams" | "crowd"
  | "roads" | "bridges" | "routes" | "shelters" | "assembly" | "medical" | "hotspots" | "traffic" | "history";

const SUS = ["var(--sus-1)", "var(--sus-2)", "var(--sus-3)", "var(--sus-4)", "var(--sus-5)"];
export const LAYERS: { key: LayerKey; label: string; icon: string; group: "scenario" | "area"; legend?: string[]; note?: string; needsRun?: boolean }[] = [
  { key: "depth", label: "Flood depth", icon: "water", group: "scenario", legend: ["var(--depth-1)", "var(--depth-2)", "var(--depth-3)", "var(--depth-4)", "var(--depth-5)"], note: "0.05 · 0.5 · 1 · 1.5 · 3+ m at the selected hour", needsRun: true },
  { key: "lsi", label: "Landslide susceptibility", icon: "landslide", group: "scenario", legend: SUS, note: "very low → very high at the selected hour", needsRun: true },
  { key: "roads", label: "Road status", icon: "road", group: "scenario", legend: ["#8c8c8c", "#f58c1e", "#d7191c"], note: "open · closes later · closed now", needsRun: true },
  { key: "routes", label: "Evacuation routes", icon: "directions_walk", group: "scenario", legend: ["#00897b"], note: "line width = people", needsRun: true },
  { key: "bridges", label: "Bridges", icon: "pin_drop", group: "scenario", legend: ["#d7191c", "#f58c1e", "#8c8c8c"], note: "closed now · closes later · stays open", needsRun: true },
  { key: "shelters", label: "Shelters", icon: "night_shelter", group: "scenario", legend: ["#1a73e8", "#9aa0a6"], note: "dot size = places filled" },
  { key: "assembly", label: "Assembly points", icon: "groups", group: "scenario", legend: ["#34a853"], needsRun: true },
  { key: "medical", label: "Medical & staging", icon: "local_hospital", group: "scenario", legend: ["#ea4335", "#9334e6"], note: "hospitals · staging points" },
  { key: "fsi", label: "Flood susceptibility", icon: "flood", group: "area", legend: SUS, note: "static index (AHP)" },
  { key: "lsi_static", label: "Landslide susceptibility (static)", icon: "terrain", group: "area", legend: SUS },
  { key: "hand", label: "Height above drainage", icon: "height", group: "area", legend: ["#08306b", "#4292c6", "#c6dbef"], note: "0 → 20 m above the nearest stream" },
  { key: "streams", label: "Streams & confluences", icon: "waves", group: "area" },
  { key: "crowd", label: "Crowding (open data)", icon: "groups_3", group: "area", legend: ["#fff3b0", "#f03b20"] },
  { key: "history", label: "Past incidents", icon: "history", group: "area", legend: ["#bd0026"], note: "reported landslides & web leads (not predictions)" },
  { key: "traffic", label: "Live traffic", icon: "traffic", group: "area", note: "display only, never used by the models" },
];

const TYPES: { t: MapType; label: string; bg: string }[] = [
  { t: "roadmap", label: "Default", bg: "linear-gradient(135deg,#e8f0e8,#f6f6f4 50%,#cfe3f5)" },
  { t: "hybrid", label: "Satellite", bg: "linear-gradient(135deg,#3d5a3c,#6b7d4f 50%,#2f4a5c)" },
  { t: "terrain", label: "Terrain", bg: "linear-gradient(135deg,#dfe7d0,#c9d7b0 50%,#b8c9a0)" },
];

/** Google Maps-style layer picker: a thumbnail button opening a sheet with map types and layer switches. */
export default function LayerPanel({ on, toggle, hasRun, mapType, setMapType }: {
  on: Set<LayerKey>; toggle: (k: LayerKey) => void; hasRun: boolean; mapType: MapType; setMapType: (t: MapType) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  const row = (l: (typeof LAYERS)[number]) => {
    const dis = l.needsRun && !hasRun;
    return (
      <div key={l.key} className={`layer-row ${dis ? "dim" : ""}`}>
        <span className="ico"><Icon name={l.icon} /></span>
        <span className="txt"><span className="t">{l.label}</span>
          {l.legend && <span className="swatches">{l.legend.map((c, i) => <i key={i} style={{ background: c }} />)}</span>}
          {l.note && <span className="s" style={{ display: "block" }}>{dis ? "Run a scenario first" : l.note}</span>}</span>
        <Switch checked={on.has(l.key)} onChange={() => toggle(l.key)} label={l.label} disabled={dis} />
      </div>
    );
  };
  return (
    <div ref={ref} style={{ position: "relative" }}>
      {open && (
        <div className="layers-sheet" style={{ position: "absolute", bottom: 92, left: 0 }} role="dialog" aria-label="Map layers">
          <div className="row nowrap" style={{ marginBottom: 8 }}><span className="title-m grow">Map type</span><IconButton icon="close" label="Close" small onClick={() => setOpen(false)} /></div>
          <div className="maptypes">
            {TYPES.map((x) => <button key={x.t} className={`maptype ${mapType === x.t ? "on" : ""}`} onClick={() => setMapType(x.t)}><i style={{ background: x.bg }} />{x.label}</button>)}
          </div>
          <hr className="divider" style={{ margin: "16px 0 8px" }} />
          <div className="title-s muted" style={{ margin: "4px 0" }}>Scenario</div>
          {LAYERS.filter((l) => l.group === "scenario").map(row)}
          <hr className="divider" style={{ margin: "8px 0" }} />
          <div className="title-s muted" style={{ margin: "4px 0" }}>Area</div>
          {LAYERS.filter((l) => l.group === "area").map(row)}
        </div>
      )}
      <button className="layers-btn" onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Layers">
        <span className="bg" style={mapType === "hybrid" ? { background: "linear-gradient(135deg,#dfe7d0,#f6f6f4)" } : undefined} />
        <span className="lt"><Icon name="layers" className="sm" /> Layers</span>
      </button>
    </div>
  );
}
