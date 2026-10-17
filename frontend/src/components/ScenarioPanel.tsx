import { useEffect, useState, type ReactNode } from "react";
import { plan, rainRecords, type RainHours as RH, type RainRecords } from "../api/client";
import type { AreaDrain, PlanResponse, RainSource, ScenarioParams, Shelter } from "../types/api";
import DrainCapacity from "./DrainCapacity";
import { PRESETS, rainSourceName } from "../rain";
import RainHours, { keyOf } from "./RainHours";
import type { DrawMode } from "./DrawControl";
import { Button, Chip, Icon, IconButton, Segmented, Slider, Switch, useSnackbar } from "./m3";

// four ways to choose the rain; each shows its own choices, then the same three for all: how strong (against the
// source's actual rain), how long, and how it is spread over the hours
type RainKind = "forecast" | "past" | "record" | "custom";
const KINDS: { value: RainKind; label: string; note: string }[] = [
  { value: "forecast", label: "Forecast", note: "Hourly forecast for this area (Google Weather), up to 10 days ahead." },
  { value: "past", label: "Past day", note: "Rain measured by satellite on a recent day (NASA GPM IMERG, about 2 days behind). Its wettest hours are used." },
  { value: "record", label: "Record", note: "How much rain falls here in one day, from 24 years of satellite records. Choose how rare a day to plan for." },
  { value: "custom", label: "Custom", note: "A standard IMD rain category, or your own intensity." },
];
const kindOf = (s: RainSource): RainKind => (s === "observed" ? "past" : s === "historical_extreme" ? "record" : s === "manual" ? "custom" : "forecast");
const fmtDay = (d: string | null) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "");
const RARITY: Record<number, { label: string; tip: string }> = {
  2: { label: "Most years", tip: "A heavy day that comes about every other year (2-year return period)" },
  10: { label: "1 in 10 years", tip: "Expected about once in 10 years (Gumbel fit to the yearly wettest days)" },
  25: { label: "1 in 25 years", tip: "Expected about once in 25 years (Gumbel fit to the yearly wettest days)" },
  100: { label: "1 in 100 years", tip: "Estimate: 24 years of records extrapolated to 100 years" },
};

/** Record rain: how rare a day, from the area's own yearly wettest days (CHIRPS 2001-2024). */
function RecordPick({ p, set }: { p: ScenarioParams; set: (patch: Partial<ScenarioParams>) => void }) {
  const [rec, setRec] = useState<RainRecords | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => { setErr(false); rainRecords(p.aoi_id).then(setRec).catch(() => setErr(true)); }, [p.aoi_id]);
  const pick = (T: ScenarioParams["return_period_y"]) => set({ return_period_y: T, rain_scale: 1 });
  return (
    <>
      <Pick label="How rare a day">
        {(rec?.levels ?? []).map((lv) => (
          <Chip small key={lv.T} label={`${RARITY[lv.T].label} · ${Math.round(lv.mm)} mm`} title={RARITY[lv.T].tip}
            selected={p.return_period_y === lv.T} onClick={() => pick(lv.T)} />
        ))}
        <Chip small label={`Wettest since ${rec?.years[0] ?? 2001}${rec ? ` · ${Math.round(rec.record.mm)} mm` : ""}`}
          title={rec?.record.date ? `The wettest day in the records: ${fmtDay(rec.record.date)}` : "The wettest day in the records"}
          selected={p.return_period_y == null} onClick={() => pick(null)} />
      </Pick>
      <p className="body-s muted rain-note">
        {rec?.record.date && p.return_period_y == null ? `That day was ${fmtDay(rec.record.date)}. ` : ""}
        {!rec && !err ? "Loading this area's records… " : ""}{err ? "Records unavailable; the wettest day is used. " : ""}
        Satellite rain (CHIRPS) averaged over about 5 km, so one rain gauge can catch more. The day's wettest hours follow the IMD rule.
      </p>
    </>
  );
}

const SOURCE_WORD: Record<RainKind, string> = { forecast: "forecast", past: "measured rain", record: "record", custom: "IMD category" };

/** "Average rain over the storm" for every source. For real data (forecast, a measured day, a record, an IMD category)
 * it starts at the data's own value and scales it; anything else is flagged as not the actual data. */
function Strength({ kind, p, set, rh }: { kind: RainKind; p: ScenarioParams; set: (patch: Partial<ScenarioParams>) => void; rh: RH | null }) {
  if (kind === "custom" && !p.rain_preset) {
    return <Slider label="Average rain over the storm" unit="mm/h" value={p.manual_intensity_mm_h} min={5} max={150}
      onChange={(v) => set({ manual_intensity_mm_h: v, preset_label: null })}
      hint="Your own intensity; the shape below sets how it is spread over the hours" />;
  }
  // runs saved with the old "worse than forecast" case: the base already holds that multiplier
  const legacy = kind === "forecast" ? (p.rain_source === "worst" ? p.worst_multiplier : p.rain_source === "best" ? p.best_multiplier : 1) : 1;
  const k = (p.rain_scale ?? 1) * legacy;
  const word = kind === "record" && p.return_period_y ? `1-in-${p.return_period_y}-year rain` : SOURCE_WORD[kind];
  if (!rh || rh.base_mean_mm_h == null) return <p className="body-s muted rain-note">Average rain over the storm: loading…</p>;
  // the source fell back to default rain (forecast or records unavailable): the backend would ignore a strength
  if (rh.scaled === null) return <p className="body-s muted rain-note">The {word} is unavailable right now, so default rain is used and its strength cannot be changed.</p>;
  const mean = rh.base_mean_mm_h / legacy, peak = (rh.base_peak_mm_h ?? 0) / legacy;
  if (peak <= 0) return <p className="body-s muted rain-note">The {word} has no rain in this window, so there is nothing to scale. Choose another day or Custom rain.</p>;
  const max = Math.max(1.05, Math.min(5, 300 / peak));
  const off = Math.abs(k - 1) > 0.001;
  const change = (v: number) => set({ rain_scale: Math.abs(v - 1) < 0.026 ? 1 : v, ...(legacy !== 1 ? { rain_source: "forecast" as const } : {}) });
  return (
    <>
      <Slider label="Average rain over the storm" value={Math.min(k, max)} min={0.25} max={max} step={0.05}
        format={(v) => `${(mean * v).toFixed(1)} mm/h`} onChange={change}
        hint={off ? undefined : `Matches the ${word}; drag to test stronger or weaker rain`} />
      {off && (
        <div className="not-actual" role="status">
          <Icon name="warning" className="sm" />
          <span className="grow">Not the actual {word}: {k > 1 ? "stronger" : "weaker"}, × {k.toFixed(2)}. Runs and briefs say so.</span>
          <Button variant="text" size="small" onClick={() => set({ rain_scale: 1, ...(legacy !== 1 ? { rain_source: "forecast" as const } : {}) })}>Back to the {SOURCE_WORD[kind]}</Button>
        </div>
      )}
    </>
  );
}

function Pick({ label, children }: { label: string; children: ReactNode }) {
  return <div className="pick"><span className="label-m muted">{label}</span><div className="chips">{children}</div></div>;
}
const FIELD_LABEL: Record<string, string> = {
  rain_source: "Rain source", manual_intensity_mm_h: "Intensity (mm/h)", duration_h: "Duration (h)", hyetograph: "Rain shape",
  forecast_day_index: "Forecast day", worst_multiplier: "Worst-case ×", river_offset_m: "River already high (m)", upstream_inflow_m3s: "Upstream river flow (m³/s)", pop_multiplier: "Population ×",
  pop_total_override: "Population total", travel_mode: "Travel", evac_start_hour: "Evacuation starts (hour)", disabled_shelter_ids: "Closed shelters",
  rain_scale: "Rain strength × (1 = actual data)", rain_shape: "Rain spread over the hours", return_period_y: "Record: once in (years)",
  bridge_margin_m: "Bridge safety margin (m)", walk_depth_limit_m: "Walk depth limit (m)", vehicle_depth_limit_m: "Vehicle depth limit (m)", max_travel_min: "Max travel (min)",
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

export default function ScenarioPanel({ p, set, replace, shelters, drawMode, setDrawMode, days, used, past, drain, onDrain, waterlogging }: {
  drain?: AreaDrain | null; onDrain?: (d: AreaDrain | null) => void; waterlogging?: boolean;
  p: ScenarioParams; set: (patch: Partial<ScenarioParams>) => void; replace: (np: ScenarioParams) => void; shelters: Shelter[];
  drawMode: DrawMode; setDrawMode: (m: DrawMode) => void; days: string[]; used?: Set<string>;
  past?: { date: string; precip_mm: number | null }[];  // observed daily rain (NASA IMERG), oldest first
}) {
  const [adv, setAdv] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [q, setQ] = useState("");
  const preset = p.rain_source === "manual" ? PRESETS.find((x) => x.id === p.rain_preset) ?? null : null;
  const toggleShelter = (id: string) => set({
    disabled_shelter_ids: p.disabled_shelter_ids.includes(id) ? p.disabled_shelter_ids.filter((x) => x !== id) : [...p.disabled_shelter_ids, id],
  });
  const [rh, setRh] = useState<(RH & { forKey: string }) | null>(null);
  const rhFresh = !!rh && rh.forKey === keyOf(p);  // the loaded hours are for exactly these settings
  const kind = kindOf(p.rain_source);
  const pickKind = (k: RainKind) => {
    if (k === kind) return;
    const latest = [...(past ?? [])].reverse().find((d) => d.precip_mm != null)?.date ?? null;
    const fresh = { rain_scale: 1, rain_shape: null, preset_label: null };  // a new source starts as its actual data
    set(k === "forecast" ? { ...fresh, rain_source: "forecast", rain_preset: null }
      : k === "past" ? { ...fresh, rain_source: "observed", rain_preset: null, observed_date: p.observed_date ?? latest }
      : k === "record" ? { ...fresh, rain_source: "historical_extreme", rain_preset: null }
      : { ...fresh, rain_source: "manual" });
  };
  // how the rain is spread over the hours, the same choice for every source; "Custom" = the bars as edited by hand
  const real = kind === "forecast" || kind === "past";
  const shapeNow = p.rain_series_override ? "custom"
    : p.rain_shape ?? (real ? "source" : p.rain_source === "manual" && p.rain_preset === "cloudburst" ? "triangular_front" : p.hyetograph);
  const shapes = [...(real ? [{ value: "source", label: kind === "forecast" ? "As forecast" : "As measured" }] : []),
    { value: "constant", label: "Steady" }, { value: "triangular_front", label: "Early peak" },
    ...(rhFresh || p.rain_series_override ? [{ value: "custom", label: "Custom" }] : [])];  // Custom needs these settings' hours loaded
  const pickShape = (v: string) => {
    if (v === "custom") {
      if (!rh || !rhFresh || p.rain_series_override) return;
      const s = rh.series.slice(0, p.duration_h);
      while (s.length < p.duration_h) s.push(0);
      set({ rain_series_override: s, override_start_local: rh.start_local, preset_label: `${rainSourceName(p)}, edited by hand` });
    } else set({ rain_shape: v as ScenarioParams["rain_shape"], rain_series_override: null, override_start_local: null, preset_label: null });
  };
  // shelters in use (or closed by you) first, then the rest; searchable, 6 shown until expanded
  const ordered = [...shelters].sort((a, b) => Number(!!used?.has(b.id) || p.disabled_shelter_ids.includes(b.id)) - Number(!!used?.has(a.id) || p.disabled_shelter_ids.includes(a.id)));
  const matches = q.trim() ? ordered.filter((s) => `${s.id} ${s.name} ${s.kind}`.toLowerCase().includes(q.trim().toLowerCase())) : ordered;
  const list = showAll || q.trim() ? matches.slice(0, 60) : matches.slice(0, 6);

  return (
    <>
      <PlanBox p={p} onApply={(np) => replace({ ...np, blocked_polygons: p.blocked_polygons, extra_shelters: p.extra_shelters })} />

      <section className="group" aria-label="Rain">
        <div className="section-title"><Icon name="rainy" /> Rain</div>
        <Segmented label="Where the rain comes from" block value={kind} onChange={pickKind}
          options={KINDS.map((k) => ({ value: k.value, label: k.label }))} />
        <p className="body-s muted rain-note">{KINDS.find((k) => k.value === kind)!.note}</p>

        {kind === "forecast" && (
          <Pick label="Day">
            <Chip small label="Wettest day" selected={p.forecast_day_index == null} onClick={() => set({ forecast_day_index: null })} />
            {days.slice(0, 10).map((d, i) => <Chip small key={d} label={d} selected={p.forecast_day_index === i} onClick={() => set({ forecast_day_index: i })} />)}
          </Pick>
        )}
        {kind === "record" && <RecordPick p={p} set={set} />}

        {kind === "past" && (() => {
          const done = (past ?? []).filter((d) => d.precip_mm != null);
          const recent = done.slice(-10).reverse();
          const wettest = [...done].sort((a, b) => (b.precip_mm ?? 0) - (a.precip_mm ?? 0)).slice(0, 3);
          const chip = (d: { date: string; precip_mm: number | null }, tag = "") => (
            <Chip small key={tag + d.date} label={`${new Date(d.date + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" })} · ${Math.round(d.precip_mm ?? 0)} mm`}
              selected={p.observed_date === d.date} onClick={() => set({ observed_date: d.date })} />);
          if (!done.length) return <p className="body-s muted">No satellite rain for this area yet.</p>;
          return (
            <>
              <Pick label="Recent days">{recent.map((d) => chip(d))}</Pick>
              {wettest.length > 0 && <Pick label="Wettest in the last 90 days">{wettest.map((d) => chip(d, "w"))}</Pick>}
            </>
          );
        })()}

        {kind === "custom" && (
          <>
            <Pick label="Type of rain">
              {PRESETS.map((pr) => <Chip small key={pr.id} label={pr.label} title={pr.note} selected={preset?.id === pr.id}
                onClick={() => set({ rain_preset: pr.id, preset_label: null, rain_scale: 1, rain_shape: null })} />)}
              <Chip small label="Your own" selected={!preset} onClick={() => set({ rain_preset: null, preset_label: null, rain_scale: 1 })} />
            </Pick>
            {preset && <p className="body-s muted rain-note">{preset.note}. Wettest hours by the IMD rule P<sub>t</sub> = P<sub>24</sub>(t/24)<sup>1/3</sup>.</p>}
          </>
        )}

        {(kind !== "past" || p.observed_date) && (
          <>
            <Strength kind={kind} p={p} set={set} rh={rh} />
            <Slider label="Duration" unit="h" value={p.duration_h} min={1} max={24}
              onChange={(v) => set({ duration_h: v, evac_start_hour: Math.min(p.evac_start_hour, v) })} />
            <Pick label="Shape">
              <Segmented label="Rain shape" block value={shapeNow} onChange={pickShape} options={shapes} />
            </Pick>
            {shapeNow === "custom" && <p className="body-s muted rain-note">Drag the bars below to set each hour; Reset goes back to the source's rain.</p>}
            <RainHours aoiId={p.aoi_id} p={p} set={set} onInfo={setRh} />
          </>
        )}
      </section>

      <section className="group" aria-label="River">
        <div className="section-title"><Icon name="water" /> River</div>
        <Slider label="River level above normal" unit="m" value={p.river_offset_m} min={-1} max={5} step={0.5} onChange={(v) => set({ river_offset_m: v })}
          hint="From the CWC gauge: today's level minus the usual monsoon level" />
        <Slider label="Upstream river flow" value={p.upstream_inflow_m3s} min={0} max={15000} step={250}
          format={(v) => (v ? `${v.toLocaleString("en-IN")} m³/s` : "local rain only")} onChange={(v) => set({ upstream_inflow_m3s: v })}
          hint="Flow arriving from outside the area, e.g. a CWC inflow forecast" />
      </section>

      {waterlogging && onDrain && (
        <section className="group" aria-label="Storm drains">
          <div className="section-title"><Icon name="plumbing" /> Storm drains</div>
          <DrainCapacity aoiId={p.aoi_id} p={p} set={set} drain={drain} onSaved={onDrain} />
        </section>
      )}

      <section className="group" aria-label="People and movement">
        <div className="section-title"><Icon name="directions_walk" /> People & movement</div>
        <Segmented label="Travel mode" block value={p.travel_mode} onChange={(v) => set({ travel_mode: v })}
          options={[{ value: "walk", label: "Walking", icon: "directions_walk" }, { value: "drive", label: "Vehicles", icon: "directions_car" }]} />
        <Slider label="Evacuation starts at hour" value={p.evac_start_hour} min={1} max={Math.max(1, p.duration_h)} onChange={(v) => set({ evac_start_hour: v })} />
        <Slider label="Pilgrims and tourists present" value={p.visitors ?? 0} min={0} max={50000} step={500}
          format={(v) => (v ? `${v.toLocaleString("en-IN")} people` : "none")} onChange={(v) => set({ visitors: v })}
          hint="Added where temples, markets and hotels concentrate people (e.g. Char Dham yatra season)" />
        <Slider label="Residents" value={p.pop_multiplier} min={0.5} max={2} step={0.1} format={(v) => `× ${v.toFixed(1)}`} onChange={(v) => set({ pop_multiplier: v })} />
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

      <section className="group">
        <button className="expand sl" aria-expanded={adv} onClick={() => setAdv(!adv)}><Icon name="tune" /> Advanced settings <Icon name="expand_more" className="chev" /></button>
        <div className={`collapse ${adv ? "open" : ""}`}><div className="stack">
          <Slider label="Walking depth limit" unit="m" value={p.walk_depth_limit_m} min={0.1} max={1.5} step={0.1} onChange={(v) => set({ walk_depth_limit_m: v })} />
          <Slider label="Vehicle depth limit" unit="m" value={p.vehicle_depth_limit_m} min={0.1} max={1} step={0.05} onChange={(v) => set({ vehicle_depth_limit_m: v })} />
          <Slider label="Close bridges before water reaches the deck by" unit="m" value={p.bridge_margin_m ?? 0} min={0} max={5} step={0.5} onChange={(v) => set({ bridge_margin_m: v })}
            hint="0 = only when the river reaches the deck. Each bridge's deck height comes from the terrain at its ends." />
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
