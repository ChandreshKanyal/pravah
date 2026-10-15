import { useState } from "react";
import type { RainSource, ScenarioParams, Shelter } from "../types/api";
import type { DrawMode } from "./DrawControl";

const SOURCES: { key: RainSource; label: string }[] = [
  { key: "forecast", label: "Forecast" }, { key: "worst", label: "Worst" }, { key: "best", label: "Best" },
  { key: "historical_extreme", label: "Historic max" }, { key: "manual", label: "Manual" },
];

function Num({ label, value, onChange, min, max, step = 1, unit }: {
  label: string; value: number; onChange: (v: number) => void; min: number; max: number; step?: number; unit?: string;
}) {
  return (
    <label className="num">
      <span>{label} <b>{value}{unit ? ` ${unit}` : ""}</b></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

export default function ScenarioPanel({ p, set, shelters, onRun, running, drawMode, setDrawMode, days }: {
  p: ScenarioParams; set: (patch: Partial<ScenarioParams>) => void; shelters: Shelter[]; onRun: () => void; running: boolean;
  drawMode: DrawMode; setDrawMode: (m: DrawMode) => void; days: string[];
}) {
  const [adv, setAdv] = useState(false);
  const toggleShelter = (id: string) => set({
    disabled_shelter_ids: p.disabled_shelter_ids.includes(id) ? p.disabled_shelter_ids.filter((x) => x !== id) : [...p.disabled_shelter_ids, id],
  });
  const usesForecast = ["forecast", "worst", "best"].includes(p.rain_source);

  return (
    <section className="scenario card" aria-label="Scenario">
      <h3>Scenario</h3>
      <div className="seg" role="radiogroup" aria-label="Rain source">
        {SOURCES.map((s) => (
          <button key={s.key} role="radio" aria-checked={p.rain_source === s.key} className={p.rain_source === s.key ? "on" : ""}
            onClick={() => set({ rain_source: s.key })}>{s.label}</button>
        ))}
      </div>
      {usesForecast && (
        <label>Forecast day
          <select value={p.forecast_day_index ?? ""} onChange={(e) => set({ forecast_day_index: e.target.value === "" ? null : Number(e.target.value) })}>
            <option value="">Wettest day</option>
            {days.map((d, i) => <option key={d} value={i}>{d}</option>)}
          </select>
        </label>
      )}
      {p.rain_source === "manual" && <Num label="Intensity" unit="mm/h" value={p.manual_intensity_mm_h} min={5} max={150} onChange={(v) => set({ manual_intensity_mm_h: v })} />}
      <Num label="Duration" unit="h" value={p.duration_h} min={1} max={24} onChange={(v) => set({ duration_h: v, evac_start_hour: Math.min(p.evac_start_hour, v) })} />
      <label>Rain shape
        <select value={p.hyetograph} onChange={(e) => set({ hyetograph: e.target.value as ScenarioParams["hyetograph"] })}>
          <option value="constant">Constant</option>
          <option value="triangular_front">Peak early (triangular)</option>
        </select>
      </label>
      <Num label="River already high by" unit="m" value={p.river_offset_m} min={-1} max={5} step={0.5} onChange={(v) => set({ river_offset_m: v })} />
      <Num label="Population ×" value={p.pop_multiplier} min={0.5} max={2} step={0.1} onChange={(v) => set({ pop_multiplier: v })} />
      <div className="seg">
        {(["walk", "drive"] as const).map((m) => (
          <button key={m} className={p.travel_mode === m ? "on" : ""} onClick={() => set({ travel_mode: m })}>{m === "walk" ? "Walk" : "Drive"}</button>
        ))}
      </div>
      <Num label="Evacuation starts at hour" value={p.evac_start_hour} min={1} max={p.duration_h} onChange={(v) => set({ evac_start_hour: v })} />

      <button className="link" onClick={() => setAdv(!adv)} aria-expanded={adv}>{adv ? "▾" : "▸"} Advanced</button>
      {adv && (
        <div className="advanced">
          <Num label="Walk depth limit" unit="m" value={p.walk_depth_limit_m} min={0.1} max={1.5} step={0.1} onChange={(v) => set({ walk_depth_limit_m: v })} />
          <Num label="Vehicle depth limit" unit="m" value={p.vehicle_depth_limit_m} min={0.1} max={1} step={0.05} onChange={(v) => set({ vehicle_depth_limit_m: v })} />
          <Num label="Bridge closes at stage" unit="m" value={p.bridge_cut_stage_m} min={1} max={10} step={0.5} onChange={(v) => set({ bridge_cut_stage_m: v })} />
          <Num label="Manning n" value={p.manning_n} min={0.02} max={0.1} step={0.005} onChange={(v) => set({ manning_n: v })} />
          <Num label="Space per person" unit="m²" value={p.sqm_per_person} min={2} max={6} step={0.5} onChange={(v) => set({ sqm_per_person: v })} />
          <Num label="Max travel time" unit="min" value={p.max_travel_min} min={15} max={180} step={5} onChange={(v) => set({ max_travel_min: v })} />
          <label>Population total override
            <input type="number" min={0} value={p.pop_total_override ?? ""} placeholder="none"
              onChange={(e) => set({ pop_total_override: e.target.value === "" ? null : Number(e.target.value) })} />
          </label>
        </div>
      )}

      <h4>Shelters <span className="muted tiny">(untick to close)</span></h4>
      <div className="shelter-toggles">
        {shelters.map((s) => (
          <label key={s.id} title={s.note || s.kind}>
            <input type="checkbox" checked={!p.disabled_shelter_ids.includes(s.id)} onChange={() => toggleShelter(s.id)} />
            {s.id} {s.name.length > 22 ? s.name.slice(0, 22) + "…" : s.name}
          </label>
        ))}
        {p.extra_shelters.map((s) => (
          <span key={s.id} className="chip">{s.name} ({s.capacity})
            <button aria-label="Remove" onClick={() => set({ extra_shelters: p.extra_shelters.filter((x) => x.id !== s.id) })}>×</button></span>
        ))}
      </div>
      <div className="row">
        <button className={drawMode === "point" ? "on" : ""} onClick={() => setDrawMode(drawMode === "point" ? null : "point")}>
          {drawMode === "point" ? "Click the map…" : "+ Add shelter"}</button>
        <button className={drawMode === "polygon" ? "on" : ""} onClick={() => setDrawMode(drawMode === "polygon" ? null : "polygon")}>
          {drawMode === "polygon" ? "Draw, double-click to end" : "Block road"}</button>
      </div>
      {p.blocked_polygons.length > 0 && (
        <div className="chips">
          {p.blocked_polygons.map((_, i) => (
            <span key={i} className="chip">Blocked area {i + 1}
              <button aria-label="Remove" onClick={() => set({ blocked_polygons: p.blocked_polygons.filter((__, j) => j !== i) })}>×</button></span>
          ))}
        </div>
      )}
      <button className="primary run" onClick={onRun} disabled={running}>{running ? "Running…" : "Run scenario"}</button>
    </section>
  );
}
