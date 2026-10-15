import { useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { RunResult } from "../types/api";
import { HelpTip, Icon, Tabs, nf } from "./m3";

const RISK_TAG: Record<string, string> = { critical: "crit", high: "high", moderate: "mod", low: "" };
const STATUS: Record<string, { label: string; tag: string; icon: string }> = {
  usable: { label: "Reachable in this scenario", tag: "ok", icon: "check_circle" },
  flooded: { label: "Flooded", tag: "info", icon: "water" },
  landslide_risk: { label: "Landslide risk", tag: "high", icon: "landslide" },
  disabled: { label: "Closed by you", tag: "", icon: "block" },
  unreachable: { label: "Unreachable", tag: "", icon: "wrong_location" },
};
const pretty = (s: string) => s.replace(/^verified_/, "verified ").replace(/_/g, " ").replace(/^likely /, "likely ") + (s.startsWith("verified_") ? " (field photo)" : " (proxy)");

function Metric({ label, value, tip, alert, icon, wide }: { label: string; value: string; tip: string; alert?: boolean; icon: string; wide?: boolean }) {
  return (
    <div className={`metric ${alert ? "alert" : ""} ${wide ? "wide" : ""}`}>
      <span className="l"><Icon name={icon} /> {label} <HelpTip text={tip} /></span>
      <span className="v">{value}</span>
    </div>
  );
}

function Chart({ data, unit, title, color }: { data: { h: number; v: number }[]; unit: string; title: string; color: string }) {
  return (
    <figure style={{ margin: 0 }}>
      <figcaption className="label-m muted" style={{ marginBottom: 4 }}>{title}</figcaption>
      <ResponsiveContainer width="100%" height={120}>
        <AreaChart data={data} margin={{ top: 6, right: 8, bottom: 2, left: -12 }}>
          <defs><linearGradient id={`g-${title}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={color} stopOpacity={0.35} /><stop offset="1" stopColor={color} stopOpacity={0.02} /></linearGradient></defs>
          <CartesianGrid vertical={false} stroke="#9aa0a6" strokeOpacity={0.25} />
          <XAxis dataKey="h" tick={{ fontSize: 11, fill: "#80868b" }} tickLine={false} axisLine={false} tickFormatter={(h) => `h${h}`} />
          <YAxis tick={{ fontSize: 11, fill: "#80868b" }} tickLine={false} axisLine={false} width={44} />
          <Tooltip formatter={(v) => [`${v} ${unit}`, title]} labelFormatter={(h) => `Hour ${h}`}
            contentStyle={{ borderRadius: 8, border: 0, boxShadow: "0 1px 3px rgba(0,0,0,.3)", fontFamily: "Google Sans" }} />
          <Area type="monotone" dataKey="v" stroke={color} strokeWidth={2} fill={`url(#g-${title})`} isAnimationActive animationDuration={450} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </figure>
  );
}

export default function Results({ run, hour, onFly, previous }: { run: RunResult; hour: number; onFly: (lon: number, lat: number) => void; previous?: RunResult | null }) {
  const [tab, setTab] = useState<"shelters" | "routes" | "bridges" | "buildings">("shelters");
  const e = run.exposure;
  const H = run.rain_series_mm_h.length;
  const peak = Math.max(0, ...e.exposed_pop_by_hour);
  const lsPeak = Math.max(0, ...e.landslide_exposed_pop_by_hour);
  const closing = run.bridges.filter((b) => b.first_closed_hour != null);
  const first = closing[0];
  const crit = (e.buildings_by_risk.critical ?? 0) + (e.buildings_by_risk.high ?? 0);
  const usable = run.shelters.filter((s) => s.status === "usable").length;
  const triage = run.triage.filter((t) => t.risk_class !== "low").slice(0, 10);
  const trig = run.methods?.landslide_trigger_hours as number[] | undefined;
  const delta = (a: number, b: number) => (b === a ? "" : ` (${b > a ? "+" : "−"}${nf(Math.abs(b - a))})`);

  return (
    <section className="stack" aria-label="Results">
      <div className="stack-s">
        <span className="label-m muted">{run.rain_label}</span>
        <p className="body-l">
          An estimated <b>{nf(run.people_to_evacuate)}</b> people need to move; <b>{usable}</b> of {run.shelters.length} shelters are reachable in this scenario
          {run.capacity_gap_people > 0 ? <>, leaving <b style={{ color: "var(--error)" }}>{nf(run.capacity_gap_people)}</b> without a place</> : <>, with room for everyone</>}.
          {first ? <> The first bridge closes at hour <b>{first.first_closed_hour}</b>.</> : null}
        </p>
      </div>

      <div className="metrics">
        <Metric icon="water" label="In flood water (peak)" value={nf(peak) + (previous ? delta(Math.max(0, ...previous.exposure.exposed_pop_by_hour), peak) : "")}
          tip="Estimated residents where water is at least 5 cm deep, at the worst hour." />
        <Metric icon="landslide" label="In landslide zones" value={nf(lsPeak)}
          tip={trig && trig.length ? `People on class 4–5 slopes in hours when rain exceeds the trigger threshold (hours ${trig.join(", ")}).` : "Rain stays below the landslide trigger threshold in this scenario, so no one is counted."} />
        <Metric icon="directions_walk" label="Need to move" value={nf(run.people_to_evacuate) + (previous ? delta(previous.people_to_evacuate, run.people_to_evacuate) : "")}
          tip="People in buildings or cells that flood, or that reach landslide class 5 above the rain threshold." />
        <Metric icon="no_accounts" label="Capacity gap" value={nf(run.capacity_gap_people) + (previous ? delta(previous.capacity_gap_people, run.capacity_gap_people) : "")}
          alert={run.capacity_gap_people > 0} tip="People who need to move but have no reachable shelter place within the travel limit." />
        <Metric icon="home_work" label="High-risk buildings" value={nf(crit)} tip="Buildings whose estimated risk (water depth damage curve, structure proxy, stream proximity, landslide) is high or critical." />
        <Metric icon="pin_drop" label="Bridges closing" value={`${closing.length} / ${run.bridges.length}`}
          tip={first ? `First: ${first.name} at hour ${first.first_closed_hour} (${first.reason}).` : "No bridge closes in this scenario."} />
      </div>

      <div className="stack-s">
        <Chart title="Flooded area" unit="km²" color="#1a73e8" data={run.flooded_area_km2_by_hour.map((v, i) => ({ h: i + 1, v }))} />
        <Chart title="People in flood water" unit="people" color="#d93025" data={e.exposed_pop_by_hour.map((v, i) => ({ h: i + 1, v }))} />
        <p className="body-s muted">Showing hour {hour} of {H}. Water never recedes within a scenario (worst-case envelope), which over-estimates on purpose.</p>
      </div>

      <div className="card outlined" style={{ padding: 0 }}>
        <Tabs value={tab} onChange={setTab} tabs={[
          { value: "shelters", label: "Shelters" }, { value: "routes", label: "Routes", badge: run.routes.filter((r) => r.use_now_gone_soon).length || undefined },
          { value: "bridges", label: "Bridges" }, { value: "buildings", label: "Buildings" },
        ]} />
        <div style={{ padding: "8px 0" }}>
          {tab === "shelters" && (
            <div className="list">
              {run.shelters.filter((s) => s.kind !== "assembly_point" || s.assigned > 0).map((s) => {
                const st = STATUS[s.status] ?? { label: s.status, tag: "", icon: "help" };
                const pct = s.capacity ? Math.min(100, (100 * s.assigned) / s.capacity) : 0;
                return (
                  <div key={s.id} className="li dense clickable sl" onClick={() => onFly(s.lon, s.lat)} role="button" tabIndex={0}>
                    <span className="label-l" style={{ width: 28, color: "var(--primary)" }}>{s.id}</span>
                    <span className="txt">
                      <span className="t" style={{ display: "block", fontSize: 14 }}>{s.name.length > 34 ? s.name.slice(0, 34) + "…" : s.name}</span>
                      <span className={`cap ${pct >= 99 ? "full" : ""}`} style={{ display: "block", margin: "4px 0" }}><i style={{ width: `${pct}%` }} /></span>
                      <span className="s">{nf(s.assigned)} of {nf(s.capacity)} places{s.capacity_confidence === "low" ? " · capacity unconfirmed" : ""}</span>
                    </span>
                    <span className={`tag ${st.tag}`}><Icon name={st.icon} />{st.label}</span>
                  </div>
                );
              })}
            </div>
          )}
          {tab === "routes" && (run.routes.length ? (
            <table className="tbl">
              <thead><tr><th>To</th><th className="r">People</th><th className="r">ETA</th><th>Passable until</th></tr></thead>
              <tbody>{run.routes.slice(0, 15).map((r, i) => (
                <tr key={i} className={r.from_lon != null ? "clickable" : ""} onClick={() => r.from_lon != null && onFly(r.from_lon, r.from_lat!)}>
                  <td><b>{r.to_shelter}</b>{r.length_km != null && <span className="body-s muted"> · {r.length_km} km</span>}</td>
                  <td className="r">{nf(r.people)}</td>
                  <td className="r" title={r.access_min ? `includes ${r.access_min} min walk to the road network` : undefined}>{r.eta_min} min</td>
                  <td>{r.passable_until_h == null ? <span className="body-s muted">whole scenario</span> : <>hour {r.passable_until_h} {r.use_now_gone_soon && <span className="tag crit">use now</span>}</>}</td>
                </tr>
              ))}</tbody>
            </table>
          ) : <p className="body-m muted" style={{ padding: 16 }}>No routes: nobody needs to move, or no shelter is reachable.</p>)}
          {tab === "bridges" && (
            <div className="list">
              {run.bridges.slice(0, 20).map((b) => (
                <div key={b.id} className="li dense clickable sl" onClick={() => onFly(b.lon, b.lat)} role="button" tabIndex={0}>
                  <span className="label-l" style={{ width: 28, color: "var(--primary)" }}>{b.id}</span>
                  <span className="txt"><span className="t" style={{ fontSize: 14 }}>{b.name}</span></span>
                  {b.first_closed_hour == null ? <span className="tag ok">stays open</span>
                    : <span className={`tag ${b.first_closed_hour <= hour ? "crit" : "high"}`}>closes hour {b.first_closed_hour} · {b.reason}</span>}
                </div>
              ))}
              {!run.bridges.length && <p className="body-m muted" style={{ padding: 16 }}>No bridges mapped in OpenStreetMap here.</p>}
            </div>
          )}
          {tab === "buildings" && (triage.length ? (
            <table className="tbl">
              <thead><tr><th>Structure</th><th>Risk</th><th className="r">Buildings</th><th className="r">People</th></tr></thead>
              <tbody>{triage.map((t) => (
                <tr key={t.structure_class + t.risk_class}><td>{pretty(t.structure_class)}</td>
                  <td><span className={`tag ${RISK_TAG[t.risk_class]}`}>{t.risk_class}</span></td><td className="r">{nf(t.buildings)}</td><td className="r">{nf(t.people)}</td></tr>
              ))}</tbody>
            </table>
          ) : <p className="body-m muted" style={{ padding: 16 }}>No buildings above low estimated risk.</p>)}
        </div>
      </div>

      {run.warnings.length > 0 && (
        <details className="card tonal">
          <summary className="row" style={{ cursor: "pointer", listStyle: "none" }}><Icon name="warning" style={{ color: "var(--warning)" }} />
            <span className="title-s grow">Notes and data gaps ({run.warnings.length})</span><Icon name="expand_more" /></summary>
          <ul className="body-s" style={{ margin: "8px 0 0", paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }}>
            {run.warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </details>
      )}
      {run.methods && (
        <p className="body-s muted"><Icon name="science" className="sm" /> {run.methods.landslide_threshold} landslide threshold · {run.methods.damage} ·{" "}
          computed in {run.timings_s.total}s</p>
      )}
    </section>
  );
}
