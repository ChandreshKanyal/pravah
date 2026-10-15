import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { RunResult } from "../types/api";

const nf = (n: number) => n.toLocaleString("en-IN");
const RISK_CLS: Record<string, string> = { critical: "r-crit", high: "r-high", moderate: "r-mod", low: "r-low" };
const STATUS: Record<string, string> = { usable: "reachable in this scenario", flooded: "flooded", landslide_risk: "landslide risk", disabled: "closed by you", unreachable: "unreachable" };
const pretty = (s: string) => s.replace(/_/g, " ").replace("likely ", "likely ");

function Card({ label, value, tip, alert }: { label: string; value: string; tip: string; alert?: boolean }) {
  return (
    <div className={`kcard ${alert ? "alert" : ""}`}>
      <div className="kval">{value}</div>
      <div className="klabel">{label} <abbr title={tip} aria-label={tip}>?</abbr></div>
    </div>
  );
}

function MiniChart({ data, y, unit, title }: { data: { h: number; v: number }[]; y: string; unit: string; title: string }) {
  return (
    <figure className="mini">
      <figcaption>{title}</figcaption>
      <ResponsiveContainer width="100%" height={110}>
        <LineChart data={data} margin={{ top: 6, right: 8, bottom: 14, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e3e3e3" />
          <XAxis dataKey="h" tick={{ fontSize: 10 }} label={{ value: "hour", position: "insideBottom", offset: -6, fontSize: 10 }} />
          <YAxis width={40} tick={{ fontSize: 10 }} label={{ value: unit, angle: -90, position: "insideLeft", fontSize: 10 }} />
          <Tooltip formatter={(v) => [`${v} ${unit}`, y]} labelFormatter={(h) => `Hour ${h}`} />
          <Line type="monotone" dataKey="v" stroke="#3182bd" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </figure>
  );
}

export default function Results({ run, hour, onFly }: { run: RunResult; hour: number; onFly: (lon: number, lat: number) => void }) {
  const e = run.exposure;
  const H = run.rain_series_mm_h.length;
  const peakExposed = Math.max(0, ...e.exposed_pop_by_hour);
  const closingBridges = run.bridges.filter((b) => b.first_closed_hour != null);
  const firstBridge = closingBridges[0];
  const critical = (e.buildings_by_risk.critical ?? 0) + (e.buildings_by_risk.high ?? 0);
  const triage = run.triage.filter((t) => t.risk_class !== "low").slice(0, 10);

  return (
    <section className="results card" aria-label="Results">
      <h3>Results <span className="muted tiny">{run.rain_label}</span></h3>
      <div className="kcards">
        <Card label="People in flood water (peak)" value={nf(peakExposed)} tip="Estimated residents where water is at least 5 cm deep, at the worst hour." />
        <Card label="High/critical buildings" value={nf(critical)} tip="Buildings whose estimated risk (depth, structure type, closeness to streams, landslide susceptibility) is high or critical." />
        <Card label="Capacity gap" value={nf(run.capacity_gap_people)} alert={run.capacity_gap_people > 0} tip="People who need to move but have no reachable shelter place in this scenario." />
        <Card label="Bridges closing" value={`${closingBridges.length}/${run.bridges.length}`} tip={firstBridge ? `First: ${firstBridge.name} at hour ${firstBridge.first_closed_hour} (${firstBridge.reason}).` : "No bridge closes in this scenario."} />
        <Card label="Routes" value={nf(run.routes.length)} tip={`${nf(run.people_to_evacuate)} people need to move; routes go to shelters reachable in this scenario.`} />
      </div>
      <div className="charts">
        <MiniChart title="Flooded area by hour" y="Flooded" unit="km²" data={run.flooded_area_km2_by_hour.map((v, i) => ({ h: i + 1, v }))} />
        <MiniChart title="People in flood water by hour" y="People" unit="people" data={e.exposed_pop_by_hour.map((v, i) => ({ h: i + 1, v }))} />
      </div>
      <p className="tiny muted">Showing hour {hour} of {H}. Water levels never recede within a scenario (worst-case envelope), which over-estimates on purpose.</p>

      <h4>Who needs help first <span className="muted tiny">(worst hour; structures, never people)</span></h4>
      {triage.length ? (
        <table className="triage">
          <thead><tr><th>Structure (proxy)</th><th>Risk</th><th>Buildings</th><th>People</th></tr></thead>
          <tbody>{triage.map((t) => (
            <tr key={t.structure_class + t.risk_class}><td>{pretty(t.structure_class)}</td>
              <td><span className={`chip ${RISK_CLS[t.risk_class]}`}>{t.risk_class}</span></td><td>{nf(t.buildings)}</td><td>{nf(t.people)}</td></tr>
          ))}</tbody>
        </table>
      ) : <p className="muted">No buildings above low risk in this scenario.</p>}

      <h4>Shelters</h4>
      <ul className="shelters">
        {run.shelters.filter((s) => s.kind !== "assembly_point" || s.assigned > 0).map((s) => (
          <li key={s.id}>
            <button className="link" onClick={() => onFly(s.lon, s.lat)}>{s.id} {s.name}</button>
            <span className={`chip st-${s.status}`}>{STATUS[s.status] ?? s.status}</span>
            <div className="bar" title={`${s.assigned} of ${s.capacity} places`}>
              <i style={{ width: `${s.capacity ? Math.min(100, (100 * s.assigned) / s.capacity) : 0}%` }} />
            </div>
            <span className="tiny">{nf(s.assigned)} / {nf(s.capacity)}{s.capacity_confidence === "low" ? " (capacity unconfirmed)" : ""}</span>
            {s.note && <div className="tiny muted">{s.note}</div>}
          </li>
        ))}
      </ul>

      <h4>Routes</h4>
      {run.routes.length ? (
        <table className="routes">
          <thead><tr><th>To</th><th>People</th><th>ETA</th><th>Passable until</th></tr></thead>
          <tbody>{run.routes.slice(0, 12).map((r, i) => (
            <tr key={i}><td>{r.to_shelter}</td><td>{nf(r.people)}</td><td>{r.eta_min} min</td>
              <td>{r.passable_until_h == null ? "whole scenario" : `hour ${r.passable_until_h}`} {r.use_now_gone_soon && <span className="chip r-high">use now</span>}</td></tr>
          ))}</tbody>
        </table>
      ) : <p className="muted">No routes: nobody needs to move, or no shelter is reachable.</p>}

      {run.warnings.length > 0 && (
        <details className="warnings" open>
          <summary>Notes and data gaps ({run.warnings.length})</summary>
          <ul>{run.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </details>
      )}
    </section>
  );
}
