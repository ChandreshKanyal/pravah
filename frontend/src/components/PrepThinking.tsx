// The Map page's side panel while an area is being prepared: a Gemini-style "thinking" view that follows the real
// preparation steps (prepare_area.py), so what it says is always what the backend is doing at that moment.
import { useEffect, useState } from "react";
import { Icon } from "./m3";

export type PrepStage = { label: string; keys: string[] };
type State = "done" | "todo" | "err";

// what each stage is doing (shown in turn while it runs) and what it says once done
const LINES: { doing: string[]; done: string }[] = [
  { doing: ["Reading the terrain, 30 m at a time", "Tracing where every slope drains", "Finding the rivers' height above drainage"], done: "Terrain and rivers mapped" },
  { doing: ["Looking at 24 years of satellite rainfall", "Checking past floods seen from space", "Mapping surface water since 1984"], done: "Rain climate and flood history read" },
  { doing: ["Reading OpenStreetMap roads", "Measuring every road segment", "Working out walking and driving times"], done: "Road network analysed" },
  { doing: ["Counting buildings from Google Open Buildings", "Placing residents in their buildings", "Estimating floors and building types"], done: "Population estimated" },
  { doing: ["Finding schools and halls that can shelter people", "Checking hospitals and clinics", "Locating bridges and their deck heights"], done: "Shelters, hospitals and bridges found" },
  { doing: ["Building the stream network", "Scoring flood susceptibility", "Looking for hollows where streets waterlog"], done: "Flood risk analysed" },
];

export default function PrepThinking({ stages, stateOf, name }: { stages: PrepStage[]; stateOf: (keys: string[]) => State; name?: string }) {
  const [tick, setTick] = useState(0);
  useEffect(() => { const t = window.setInterval(() => setTick((x) => x + 1), 2600); return () => clearInterval(t); }, []);
  const states = stages.map((g) => stateOf(g.keys));
  const active = states.findIndex((s) => s === "todo");
  const lines = LINES[active] ?? LINES[LINES.length - 1];
  const now = active < 0 ? "Finishing up" : lines.doing[tick % lines.doing.length];
  return (
    <div className="prep-think" role="status" aria-live="polite">
      <div className="pt-head">
        <span className="pt-spark" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="30" height="30"><defs><linearGradient id="ptspark" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#4285f4" /><stop offset=".55" stopColor="#9b72cb" /><stop offset="1" stopColor="#d96570" /></linearGradient></defs>
            <path fill="url(#ptspark)" d="M12 2c.6 4.8 4.4 9.4 10 10-5.6.6-9.4 5.2-10 10-.6-4.8-4.4-9.4-10-10 5.6-.6 9.4-5.2 10-10z" /></svg>
        </span>
        <div>
          <div className="title-m">Analysing {name && name !== "Unnamed area" ? name : "this area"}</div>
          <div key={now} className="pt-now asst-shimmer">{now}…</div>
        </div>
      </div>
      <div className="pt-bars" aria-hidden="true"><i /><i /><i /></div>
      <ul className="pt-steps">
        {stages.map((g, i) => states[i] === "todo" && i !== active ? null : (
          <li key={g.label} className={states[i]}>
            <Icon name={states[i] === "done" ? "check_circle" : states[i] === "err" ? "error" : "progress_activity"} className={`sm ${states[i] === "todo" ? "spin" : ""}`} />
            {states[i] === "done" ? LINES[i]?.done ?? g.label : states[i] === "err" ? `${g.label}: partly unavailable` : g.label}
          </li>
        ))}
      </ul>
      <p className="body-s muted">The scenario settings appear here when the area is ready.</p>
    </div>
  );
}
