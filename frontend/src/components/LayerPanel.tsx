import { useEffect, useRef, useState } from "react";
import type { MapType } from "./MapCanvas";
import { Icon, IconButton, Switch } from "./m3";
import { Sym, type SymKey } from "./MapLegend";

export type LayerKey =
  | "depth" | "fsi" | "hand" | "streams" | "crowd" | "roads" | "bridges" | "routes" | "shelters"
  | "all_shelters" | "assembly" | "staging" | "medical" | "hotspots" | "traffic" | "history" | "ponding" | "drains";
/** Shaded layers that share a colour ramp replace each other, so a colour on the map has one meaning at a time. */
export const SHADE_FAMILY: Partial<Record<LayerKey, "blue" | "warm">> = {
  depth: "blue", ponding: "blue", hand: "blue", fsi: "warm", crowd: "warm",
};

export const LAYERS: { key: LayerKey; label: string; icon: string; group: "scenario" | "area"; syms?: SymKey[]; note?: string; needsRun?: boolean }[] = [
  { key: "depth", label: "Flood depth", icon: "water", group: "scenario", syms: ["depth", "water"], note: "5 cm → 3 m+ · normal river level", needsRun: true },
  { key: "ponding", label: "Ponding likelihood", icon: "water_drop", group: "scenario", syms: ["ponding"], note: "low → high (fill ≥ 30 / 70 %)", needsRun: true },
  { key: "drains", label: "Drains to inspect", icon: "plumbing", group: "scenario", syms: ["drain"], note: "D1 = highest priority", needsRun: true },
  { key: "roads", label: "Road status", icon: "road", group: "scenario", syms: ["roadOpen", "roadLater", "roadClosed"], note: "open · closes later · closed", needsRun: true },
  { key: "routes", label: "Evacuation routes", icon: "directions_walk", group: "scenario", syms: ["route", "routeClosed"], note: "width = people · dashed = closed", needsRun: true },
  { key: "bridges", label: "Bridges that close", icon: "do_not_disturb_on", group: "scenario", syms: ["bridgeLater", "bridgeClosed"], note: "the rest stay open (see Results)", needsRun: true },
  { key: "shelters", label: "Shelters in use", icon: "night_shelter", group: "scenario", syms: ["shelter"], note: "bigger = more places filled" },
  { key: "all_shelters", label: "All candidate shelters", icon: "holiday_village", group: "scenario", syms: ["candidate"], note: "schools, halls, temples (OSM)" },
  { key: "assembly", label: "Assembly points", icon: "groups", group: "scenario", syms: ["assembly"], needsRun: true },
  { key: "staging", label: "Staging points", icon: "local_shipping", group: "scenario", syms: ["staging"], note: "for response teams", needsRun: true },
  { key: "medical", label: "Hospitals & clinics", icon: "local_hospital", group: "scenario", syms: ["medical"], note: "from OpenStreetMap" },
  { key: "fsi", label: "Flood susceptibility", icon: "flood", group: "area", syms: ["fsi"], note: "static index (AHP)" },
  { key: "hand", label: "Height above drainage", icon: "height", group: "area", syms: ["hand"], note: "0 → 20 m above nearest stream" },
  { key: "streams", label: "Streams & confluences", icon: "waves", group: "area", syms: ["stream", "hotspot"], note: "dots = flow hotspots" },
  { key: "crowd", label: "Crowding (open data)", icon: "groups_3", group: "area", syms: ["crowdShade", "crowd"] },
  { key: "history", label: "Past incidents", icon: "history", group: "area", syms: ["webReport"], note: "records, not predictions", needsRun: true },
  { key: "traffic", label: "Live traffic", icon: "traffic", group: "area", syms: ["traffic"], note: "display only, not used by models" },
];

const TYPES: { t: MapType; label: string; bg: string }[] = [
  { t: "roadmap", label: "Default", bg: "linear-gradient(135deg,#e8f0e8,#f6f6f4 50%,#cfe3f5)" },
  { t: "hybrid", label: "Satellite", bg: "linear-gradient(135deg,#3d5a3c,#6b7d4f 50%,#2f4a5c)" },
  { t: "terrain", label: "Terrain", bg: "linear-gradient(135deg,#dfe7d0,#c9d7b0 50%,#b8c9a0)" },
];

/** Google Maps-style layer picker: a thumbnail button opening a sheet with map types and layer switches. */
export default function LayerPanel({ on, toggle, hasRun, mapType, setMapType, urban }: {
  on: Set<LayerKey>; toggle: (k: LayerKey) => void; hasRun: boolean; mapType: MapType; setMapType: (t: MapType) => void; urban?: boolean;
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
          {l.syms && <span className="swatches">{l.syms.map((k) => <Sym key={k} k={k} small />)}</span>}
          {l.note && <span className="s" style={{ display: "block" }}>{dis ? "Run a scenario first" : l.note}</span>}</span>
        <Switch checked={on.has(l.key)} onChange={() => toggle(l.key)} label={l.label} disabled={dis} />
      </div>
    );
  };
  return (
    <div ref={ref} style={{ position: "relative" }}>
      {open && (
        <div className="layers-sheet" style={{ position: "absolute", bottom: 68, left: 0 }} role="dialog" aria-label="Map layers">
          <div className="row nowrap" style={{ marginBottom: 8 }}><span className="title-m grow">Map type</span><IconButton icon="close" label="Close" small onClick={() => setOpen(false)} /></div>
          <div className="maptypes">
            {TYPES.map((x) => <button key={x.t} className={`maptype ${mapType === x.t ? "on" : ""}`} onClick={() => setMapType(x.t)}><i style={{ background: x.bg }} />{x.label}</button>)}
          </div>
          <hr className="divider" style={{ margin: "16px 0 8px" }} />
          <div className="title-s muted" style={{ margin: "4px 0" }}>Scenario</div>
          {LAYERS.filter((l) => l.group === "scenario" && (urban || !["ponding", "drains"].includes(l.key))).map(row)}
          <hr className="divider" style={{ margin: "8px 0" }} />
          <div className="title-s muted" style={{ margin: "4px 0" }}>Area</div>
          {LAYERS.filter((l) => l.group === "area").map(row)}
          <p className="body-s muted" style={{ marginTop: 8 }}>Shaded layers with the same colours replace each other.</p>
        </div>
      )}
      <button className="layers-btn" onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Layers">
        <span className="bg" style={mapType === "hybrid" ? { background: "linear-gradient(135deg,#dfe7d0,#f6f6f4)" } : undefined} />
        <span className="lt"><Icon name="layers" className="sm" /> Layers</span>
      </button>
    </div>
  );
}
