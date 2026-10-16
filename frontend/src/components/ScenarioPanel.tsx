import { useState } from "react";
import { plan } from "../api/client";
import type { PlanResponse, RainSource, ScenarioParams, Shelter } from "../types/api";
import type { DrawMode } from "./DrawControl";
import { useMode } from "../mode";
import { Button, Chip, Icon, IconButton, Segmented, Slider, Switch, useSnackbar } from "./m3";

// IMD 24-hour rainfall categories (mm/day): heavy 64.5-115.5, very heavy 115.6-204.4, extremely heavy >= 204.5;
// cloudburst >= 100 mm in an hour. A daily total becomes the wettest H hours by the IMD reduction rule
// P_H = P_24 (H/24)^(1/3) (the same rule the model uses for the historical extreme), spread evenly.
const PRESETS = [
  { id: "heavy", label: "IMD heavy", day: 115.5, note: "64.5–115.5 mm/day" },
  { id: "very_heavy", label: "IMD very heavy", day: 204.4, note: "115.6–204.4 mm/day" },
  { id: "extreme", label: "IMD extremely heavy", day: 300, note: "≥ 204.5 mm/day (300 used)" },
  { id: "cloudburst", label: "Cloudburst", day: 0, note: "100 mm in one hour" },
] as const;
function presetParams(id: string, H: number): Partial<ScenarioParams> {
  const pr = PRESETS.find((x) => x.id === id)!;
  if (pr.id === "cloudburst") return { rain_source: "manual", manual_intensity_mm_h: 100, duration_h: Math.max(1, H), hyetograph: "triangular_front",
    preset_label: `Cloudburst: 100 mm/h peak (IMD definition), ${Math.max(1, H)} h, early peak` };
  const depth = pr.day * Math.pow(Math.min(H, 24) / 24, 1 / 3);
  return { rain_source: "manual", manual_intensity_mm_h: Math.round((depth / H) * 10) / 10, hyetograph: "constant",
    preset_label: `${pr.label} rain (${pr.note}): ${pr.day} mm day, wettest ${H} h = ${Math.round(depth)} mm` };
}

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

export default function ScenarioPanel({ p, set, replace, shelters, drawMode, setDrawMode, days, used }: {
  p: ScenarioParams; set: (patch: Partial<ScenarioParams>) => void; replace: (np: ScenarioParams) => void; shelters: Shelter[];
  drawMode: DrawMode; setDrawMode: (m: DrawMode) => void; days: string[]; used?: Set<string>;
}) {
  const mode = useMode();
  const [adv, setAdv] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [q, setQ] = useState("");
  const preset = PRESETS.find((x) => p.preset_label?.startsWith(x.label))?.id ?? null;
  const toggleShelter = (id: string) => set({
    disabled_shelter_ids: p.disabled_shelter_ids.includes(id) ? p.disabled_shelter_ids.filter((x) => x !== id) : [...p.disabled_shelter_ids, id],
  });
  const usesForecast = ["forecast", "worst", "best"].includes(p.rain_source);
  // shelters in use (or closed by you) first, then the rest; searchable, 6 shown until expanded
  const ordered = [...shelters].sort((a, b) => Number(!!used?.has(b.id) || p.disabled_shelter_ids.includes(b.id)) - Number(!!used?.has(a.id) || p.disabled_shelter_ids.includes(a.id)));
  const matches = q.trim() ? ordered.filter((s) => `${s.id} ${s.name} ${s.kind}`.toLowerCase().includes(q.trim().toLowerCase())) : ordered;
  const list = showAll || q.trim() ? matches.slice(0, 60) : matches.slice(0, 6);

  return (
    <>
      <PlanBox p={p} onApply={(np) => replace({ ...np, blocked_polygons: p.blocked_polygons, extra_shelters: p.extra_shelters })} />

      <section className="group" aria-label="Rain">
        <div className="section-title"><Icon name="rainy" /> Rain</div>
        <Segmented label="Rain source" block value={["best"].includes(p.rain_source) ? "forecast" : p.rain_source} onChange={(v) => set({ rain_source: v, preset_label: null })}
          options={SOURCES.map((s) => ({ value: s.value, label: s.label }))} />
        <div className="chips" role="group" aria-label="IMD rain categories">
          {PRESETS.map((pr) => <Chip key={pr.id} label={pr.label} title={pr.note} selected={p.rain_source === "manual" && preset === pr.id}
            onClick={() => set(presetParams(pr.id, p.duration_h))} />)}
        </div>
        {usesForecast && (
          <div className="chips">
            <Chip label="Wettest day" selected={p.forecast_day_index == null} onClick={() => set({ forecast_day_index: null })} />
            {days.slice(0, 10).map((d, i) => <Chip key={d} label={d} selected={p.forecast_day_index === i} onClick={() => set({ forecast_day_index: i })} />)}
          </div>
        )}
        {p.rain_source === "worst" && <Slider label="Worst case" value={p.worst_multiplier} min={1} max={3} step={0.1} format={(v) => `forecast × ${v.toFixed(1)}`} onChange={(v) => set({ worst_multiplier: v })} />}
        {p.rain_source === "historical_extreme" && <p className="body-s muted">The wettest day on record nearby (CHIRPS 2001–2024), with its wettest hours by the IMD reduction rule.</p>}
        {p.rain_source === "manual" && preset && <p className="body-s muted">{p.preset_label}</p>}
        {p.rain_source === "manual" && !preset && <Slider label="Intensity" unit="mm/h" value={p.manual_intensity_mm_h} min={5} max={150} onChange={(v) => set({ manual_intensity_mm_h: v, preset_label: null })} />}
        <Slider label="Duration" unit="h" value={p.duration_h} min={1} max={24}
          onChange={(v) => set({ duration_h: v, evac_start_hour: Math.min(p.evac_start_hour, v), ...(preset ? presetParams(preset, v) : {}) })} />
        {mode === "analyst" && <Segmented label="Rain shape" block value={p.hyetograph} onChange={(v) => set({ hyetograph: v })}
          options={[{ value: "constant", label: "Steady" }, { value: "triangular_front", label: "Early peak" }]} />}
        <Slider label="River level above normal" unit="m" value={p.river_offset_m} min={-1} max={5} step={0.5} onChange={(v) => set({ river_offset_m: v })}
          hint="From the CWC gauge: today's level minus the usual monsoon level" />
      </section>

      <section className="group" aria-label="People and movement">
        <div className="section-title"><Icon name="directions_walk" /> People & movement</div>
        <Segmented label="Travel mode" block value={p.travel_mode} onChange={(v) => set({ travel_mode: v })}
          options={[{ value: "walk", label: "Walking", icon: "directions_walk" }, { value: "drive", label: "Vehicles", icon: "directions_car" }]} />
        <Slider label="Evacuation starts at hour" value={p.evac_start_hour} min={1} max={Math.max(1, p.duration_h)} onChange={(v) => set({ evac_start_hour: v })} />
        <Slider label="Pilgrims and tourists present" value={p.visitors ?? 0} min={0} max={50000} step={500}
          format={(v) => (v ? `${v.toLocaleString("en-IN")} people` : "none")} onChange={(v) => set({ visitors: v })}
          hint="Added where temples, markets and hotels concentrate people (e.g. Char Dham yatra season)" />
        {mode === "analyst" && <Slider label="Residents" value={p.pop_multiplier} min={0.5} max={2} step={0.1} format={(v) => `× ${v.toFixed(1)}`} onChange={(v) => set({ pop_multiplier: v })} />}
      </section>

      <section className="group" aria-label="Shelters">
        <div className="section-title"><Icon name="night_shelter" /> Shelters <span className="body-s muted">· {shelters.length} found · switch off to close</span></div>
        {shelters.length > 6 && <div className="search small"><Icon name="search" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a shelter by name or id" aria-label="Find a shelter" /></div>}
        <div className="list">
          {list.map((s) => (
            <div key={s.id} className="layer-row" title={s.note || s.kind}>
              <span className="ico" style={{ background: "var(--primary-container)", color: "var(--on-primary-container)" }}><span className="label-m">{s.id}</span></span>
              <span className="txt"><span className="t">{s.name.length > 30 ? s.name.slice(0, 30) + "…" : s.name}</span>
                <span className="s" style={{ display: "block" }}>{used?.has(s.id) ? "in use · " : ""}{s.kind.replace(/_/g, " ")}{s.capacity_confidence === "low" ? " · capacity unconfirmed" : ""}</span></span>
              <Switch checked={!p.disabled_shelter_ids.includes(s.id)} onChange={() => toggleShelter(s.id)} label={`Shelter ${s.id} open`} />
            </div>
          ))}
          {!q.trim() && shelters.length > 6 && <Button variant="text" size="small" icon={showAll ? "expand_less" : "expand_more"} onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer" : `Show more (${Math.min(60, shelters.length)} of ${shelters.length})`}</Button>}
          {q.trim() && !matches.length && <p className="body-s muted">No shelter matches “{q}”.</p>}
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

      {mode === "analyst" && <section className="group">
        <button className="expand sl" aria-expanded={adv} onClick={() => setAdv(!adv)}><Icon name="tune" /> Advanced settings <Icon name="expand_more" className="chev" /></button>
        <div className={`collapse ${adv ? "open" : ""}`}><div className="stack">
          <Slider label="Upstream river flow" value={p.upstream_inflow_m3s} min={0} max={15000} step={250}
            format={(v) => (v ? `${v.toLocaleString("en-IN")} m³/s` : "local rain only")} onChange={(v) => set({ upstream_inflow_m3s: v })}
            hint="Flow arriving from outside the area, e.g. a CWC inflow forecast" />
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
      </section>}
    </>
  );
}
