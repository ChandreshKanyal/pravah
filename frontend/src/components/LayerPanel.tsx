export type LayerKey =
  | "depth" | "lsi" | "fsi" | "lsi_static" | "hand" | "streams" | "crowd"
  | "roads" | "bridges" | "routes" | "shelters" | "assembly" | "medical" | "hotspots" | "traffic";

export const LAYERS: { key: LayerKey; label: string; legend?: string[]; legendNote?: string; needsRun?: boolean }[] = [
  { key: "depth", label: "Flood depth (hour t)", legend: ["#c6dbef", "#9ecae1", "#6baed6", "#3182bd", "#08519c"], legendNote: "0.05 · 0.5 · 1 · 1.5 · 3+ m", needsRun: true },
  { key: "lsi", label: "Landslide susceptibility (hour t)", legend: ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"], legendNote: "very low → very high", needsRun: true },
  { key: "roads", label: "Roads status", legend: ["#8c8c8c", "#f58c1e", "#d7191c"], legendNote: "open · closes later · closed now", needsRun: true },
  { key: "routes", label: "Evacuation routes", legend: ["#009688"], legendNote: "width = people", needsRun: true },
  { key: "shelters", label: "Shelters", legend: ["#2166ac", "#787878"], legendNote: "usable · not usable" },
  { key: "assembly", label: "Assembly points", legend: ["#4daf4a"], needsRun: true },
  { key: "bridges", label: "Bridges", legend: ["#d7191c", "#f58c1e", "#8c8c8c"], legendNote: "closes now · later · stays open", needsRun: true },
  { key: "medical", label: "Medical & staging", legend: ["#e41a1c", "#984ea3"], legendNote: "hospitals · staging" },
  { key: "fsi", label: "Flood susceptibility (FSI)", legend: ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"] },
  { key: "lsi_static", label: "Landslide susceptibility (static)", legend: ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"] },
  { key: "hand", label: "Height above drainage (HAND)", legend: ["#08306b", "#4292c6", "#c6dbef"], legendNote: "0 → 20 m" },
  { key: "streams", label: "Streams & convergence hotspots", legend: ["#08306b", "#ffffff"] },
  { key: "crowd", label: "Crowding (open data)", legend: ["#ffffb2", "#f03b20"] },
  { key: "traffic", label: "Live traffic (display only)" },
];

export default function LayerPanel({ on, toggle, hasRun }: { on: Set<LayerKey>; toggle: (k: LayerKey) => void; hasRun: boolean }) {
  return (
    <nav className="layer-panel card" aria-label="Map layers">
      <h3>Layers</h3>
      {LAYERS.map((l) => (
        <label key={l.key} className={`layer ${l.needsRun && !hasRun ? "dim" : ""}`}>
          <input type="checkbox" checked={on.has(l.key)} onChange={() => toggle(l.key)} disabled={l.needsRun && !hasRun} />
          <span>{l.label}</span>
          {l.legend && on.has(l.key) && (
            <span className="legend">
              {l.legend.map((c) => <i key={c} style={{ background: c }} />)}
              {l.legendNote && <em>{l.legendNote}</em>}
            </span>
          )}
        </label>
      ))}
      <p className="tiny muted">Traffic and Street View are for people to look at; Pravah never reads them into its models.</p>
    </nav>
  );
}
