import { useState } from "react";
import { plan } from "../api/client";
import type { PlanResponse, RainSource, ScenarioParams, Shelter } from "../types/api";
import type { DrawMode } from "./DrawControl";
import { Button, Chip, Icon, IconButton, Segmented, Slider, Switch, useSnackbar } from "./m3";

const SOURCES: { value: RainSource; label: string; icon: string }[] = [
  { value: "forecast", label: "Forecast", icon: "cloud" }, { value: "worst", label: "Worst", icon: "thunderstorm" },
  { value: "historical_extreme", label: "Record", icon: "history" }, { value: "manual", label: "Custom", icon: "tune" },
];
const FIELD_LABEL: Record<string, string> = {
  rain_source: "Rain source", manual_intensity_mm_h: "Intensity (mm/h)", duration_h: "Duration (h)", hyetograph: "Rain shape",
  forecast_day_index: "Forecast day", worst_multiplier: "Worst-case ×", river_offset_m: "River already high (m)", upstream_inflow_m3s: "Upstream river flow (m³/s)", pop_multiplier: "Population ×",
  pop_total_override: "Population total", travel_mode: "Travel", evac_start_hour: "Evacuation starts (hour)", disabled_shelter_ids: "Closed shelters",
  bridge_cut_stage_m: "Bridge closes at (m)", walk_depth_limit_m: "Walk depth limit (m)", vehicle_depth_limit_m: "Vehicle depth limit (m)", max_travel_min: "Max travel (min)",
};
const show = (v: unknown) => (Array.isArray(v) ? (v.length ? v.join(", ") : "none") : v == null ? "auto" : String(v));

function PlanBox({ p, onApply }: { p: ScenarioParams; onApply: (np: ScenarioParams) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<PlanResponse | null>(null);
  const snack = useSnackbar();
  async function go() {
    if (!text.trim()) return;
    setBusy(true);
    setRes(null);
    try { setRes(await plan(p.aoi_id, text, p)); } catch (e) { snack(String((e as Error).message)); } finally { setBusy(false); }
  }
  const keys = res ? Object.keys(res.diff) : [];
  return (
    <div className="plan">
      <div className="inner">
        <div className="row nowrap"><Icon name="auto_awesome" className="gemini-text" /><span className="title-s grow">Describe a scenario</span>
          {busy && <span className="spinner small" />}</div>
        <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder='e.g. "80 mm an hour for 3 hours, and close the temple shelter"'
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(); } }} aria-label="Describe a scenario" />
        {res && (
          <div className="stack-s">
            {keys.length ? (
              <div className="diff">
                {keys.map((k) => <div key={k}><span className="k">{FIELD_LABEL[k] ?? k}: </span><s>{show(res.diff[k][0])}</s> → <b>{show(res.diff[k][1])}</b></div>)}
              </div>
            ) : <span className="body-s muted">No changes found in that request.</span>}
            {res.explanation && <span className="body-s muted">{res.explanation}</span>}
          </div>
        )}
        <div className="row">
          <span className="body-s muted grow">Gemini suggests settings; you review and apply.</span>
          {res && keys.length > 0 ? (
            <>
              <Button variant="text" size="small" onClick={() => setRes(null)}>Discard</Button>
              <Button size="small" icon="check" onClick={() => { onApply(res.params); setRes(null); setText(""); snack("Settings applied. Press Run scenario."); }}>Apply</Button>
            </>
          ) : <Button variant="tonal" size="small" icon="arrow_upward" disabled={busy || !text.trim()} onClick={go}>Suggest</Button>}
        </div>
      </div>
    </div>
  );
}

export default function ScenarioPanel({ p, set, replace, shelters, drawMode, setDrawMode, days }: {
  p: ScenarioParams; set: (patch: Partial<ScenarioParams>) => void; replace: (np: ScenarioParams) => void; shelters: Shelter[];
  drawMode: DrawMode; setDrawMode: (m: DrawMode) => void; days: string[];
}) {
  const [adv, setAdv] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const toggleShelter = (id: string) => set({
    disabled_shelter_ids: p.disabled_shelter_ids.includes(id) ? p.disabled_shelter_ids.filter((x) => x !== id) : [...p.disabled_shelter_ids, id],
  });
  const usesForecast = ["forecast", "worst", "best"].includes(p.rain_source);
  const list = showAll ? shelters : shelters.slice(0, 6);

  return (
    <>
      <PlanBox p={p} onApply={(np) => replace({ ...np, blocked_polygons: p.blocked_polygons, extra_shelters: p.extra_shelters })} />

      <section className="group" aria-label="Rain">
        <div className="section-title"><Icon name="rainy" /> Rain</div>
        <Segmented label="Rain source" block value={["best"].includes(p.rain_source) ? "forecast" : p.rain_source} onChange={(v) => set({ rain_source: v })}
          options={SOURCES.map((s) => ({ value: s.value, label: s.label }))} />
        {usesForecast && (
          <div className="chips">
            <Chip label="Wettest day" selected={p.forecast_day_index == null} onClick={() => set({ forecast_day_index: null })} />
            {days.slice(0, 10).map((d, i) => <Chip key={d} label={d} selected={p.forecast_day_index === i} onClick={() => set({ forecast_day_index: i })} />)}
          </div>
        )}
        {p.rain_source === "worst" && <Slider label="Worst case" value={p.worst_multiplier} min={1} max={3} step={0.1} format={(v) => `forecast × ${v.toFixed(1)}`} onChange={(v) => set({ worst_multiplier: v })} />}
        {p.rain_source === "historical_extreme" && <p className="body-s muted">The wettest day on record nearby (CHIRPS 2001–2024), with its wettest hours by the IMD reduction rule.</p>}
        {p.rain_source === "manual" && <Slider label="Intensity" unit="mm/h" value={p.manual_intensity_mm_h} min={5} max={150} onChange={(v) => set({ manual_intensity_mm_h: v })} />}
        <Slider label="Duration" unit="h" value={p.duration_h} min={1} max={24} onChange={(v) => set({ duration_h: v, evac_start_hour: Math.min(p.evac_start_hour, v) })} />
        <Segmented label="Rain shape" block value={p.hyetograph} onChange={(v) => set({ hyetograph: v })}
          options={[{ value: "constant", label: "Steady" }, { value: "triangular_front", label: "Early peak" }]} />
        <Slider label="River already high by" unit="m" value={p.river_offset_m} min={-1} max={5} step={0.5} onChange={(v) => set({ river_offset_m: v })} />
        <Slider label="Upstream river flow" value={p.upstream_inflow_m3s} min={0} max={15000} step={250}
          format={(v) => (v ? `${v.toLocaleString("en-IN")} m³/s` : "local rain only")} onChange={(v) => set({ upstream_inflow_m3s: v })}
          hint="Flow arriving from outside the area, e.g. a CWC flood forecast" />
      </section>

      <section className="group" aria-label="People and movement">
        <div className="section-title"><Icon name="directions_walk" /> People & movement</div>
        <Segmented label="Travel mode" block value={p.travel_mode} onChange={(v) => set({ travel_mode: v })}
          options={[{ value: "walk", label: "Walking", icon: "directions_walk" }, { value: "drive", label: "Vehicles", icon: "directions_car" }]} />
        <Slider label="Evacuation starts at hour" value={p.evac_start_hour} min={1} max={Math.max(1, p.duration_h)} onChange={(v) => set({ evac_start_hour: v })} />
        <Slider label="Population" value={p.pop_multiplier} min={0.5} max={2} step={0.1} format={(v) => `× ${v.toFixed(1)}`} onChange={(v) => set({ pop_multiplier: v })} />
      </section>

      <section className="group" aria-label="Shelters">
        <div className="section-title"><Icon name="night_shelter" /> Shelters <span className="body-s muted">· switch off to close</span></div>
        <div className="list">
          {list.map((s) => (
            <div key={s.id} className="layer-row" title={s.note || s.kind}>
              <span className="ico" style={{ background: "var(--primary-container)", color: "var(--on-primary-container)" }}><span className="label-m">{s.id}</span></span>
              <span className="txt"><span className="t">{s.name.length > 30 ? s.name.slice(0, 30) + "…" : s.name}</span>
                <span className="s" style={{ display: "block" }}>{s.kind.replace(/_/g, " ")}{s.capacity_confidence === "low" ? " · capacity unconfirmed" : ""}</span></span>
              <Switch checked={!p.disabled_shelter_ids.includes(s.id)} onChange={() => toggleShelter(s.id)} label={`Shelter ${s.id} open`} />
            </div>
          ))}
          {shelters.length > 6 && <Button variant="text" size="small" icon={showAll ? "expand_less" : "expand_more"} onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer" : `Show all ${shelters.length}`}</Button>}
        </div>
        {(p.extra_shelters.length > 0 || p.blocked_polygons.length > 0) && (
          <div className="chips">
            {p.extra_shelters.map((s) => <Chip key={s.id} icon="add_home" label={`${s.name} · ${s.capacity}`} onRemove={() => set({ extra_shelters: p.extra_shelters.filter((x) => x.id !== s.id) })} />)}
            {p.blocked_polygons.map((_, i) => <Chip key={i} icon="block" label={`Blocked area ${i + 1}`} onRemove={() => set({ blocked_polygons: p.blocked_polygons.filter((__, j) => j !== i) })} />)}
          </div>
        )}
        <div className="row">
          <Button variant={drawMode === "point" ? "filled" : "outlined"} size="small" icon="add_home" onClick={() => setDrawMode(drawMode === "point" ? null : "point")}>
            {drawMode === "point" ? "Click the map…" : "Add shelter"}</Button>
          <Button variant={drawMode === "polygon" ? "filled" : "outlined"} size="small" icon="block" onClick={() => setDrawMode(drawMode === "polygon" ? null : "polygon")}>
            {drawMode === "polygon" ? "Double-click to finish" : "Block a road"}</Button>
        </div>
      </section>

      <section className="group">
        <button className="expand sl" aria-expanded={adv} onClick={() => setAdv(!adv)}><Icon name="tune" /> Advanced settings <Icon name="expand_more" className="chev" /></button>
        <div className={`collapse ${adv ? "open" : ""}`}><div className="stack">
          <Slider label="Walking depth limit" unit="m" value={p.walk_depth_limit_m} min={0.1} max={1.5} step={0.1} onChange={(v) => set({ walk_depth_limit_m: v })} />
          <Slider label="Vehicle depth limit" unit="m" value={p.vehicle_depth_limit_m} min={0.1} max={1} step={0.05} onChange={(v) => set({ vehicle_depth_limit_m: v })} />
          <Slider label="Bridge closes when river is" unit="m" value={p.bridge_cut_stage_m} min={1} max={10} step={0.5} onChange={(v) => set({ bridge_cut_stage_m: v })} />
          <Slider label="Channel roughness (Manning n)" value={p.manning_n} min={0.02} max={0.1} step={0.005} format={(v) => v.toFixed(3)} onChange={(v) => set({ manning_n: v })} />
          <Slider label="Space per person in shelters" unit="m²" value={p.sqm_per_person} min={2} max={6} step={0.5} onChange={(v) => set({ sqm_per_person: v })} />
          <Slider label="Longest acceptable trip" unit="min" value={p.max_travel_min} min={15} max={180} step={5} onChange={(v) => set({ max_travel_min: v })} />
          <div className="row nowrap">
            <span className="body-m grow">Population total override</span>
            <input className="mono" style={{ width: 120, height: 40, borderRadius: 4, border: "1px solid var(--outline)", padding: "0 12px", background: "transparent", color: "var(--on-surface)" }}
              type="number" min={0} value={p.pop_total_override ?? ""} placeholder="none" aria-label="Population total override"
              onChange={(e) => set({ pop_total_override: e.target.value === "" ? null : Number(e.target.value) })} />
            {p.pop_total_override != null && <IconButton icon="close" label="Clear override" small onClick={() => set({ pop_total_override: null })} />}
          </div>
        </div></div>
      </section>
    </>
  );
}
