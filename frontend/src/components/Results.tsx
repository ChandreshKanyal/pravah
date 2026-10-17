import { Link } from "react-router-dom";
import { useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { RunResult } from "../types/api";
import { REASON, deckLine, markerUrl, routeClosed } from "../layers/factories";
import ModelCheck from "./ModelCheck";
import { before, clockAt, roundPeople } from "../time";
import { HelpTip, Icon, Tabs, nf } from "./m3";

const RISK_TAG: Record<string, string> = { critical: "crit", high: "high", moderate: "mod", low: "" };
const STATUS: Record<string, { label: string; tag: string; icon: string }> = {
  usable: { label: "Reachable in this scenario", tag: "ok", icon: "check_circle" },
  flooded: { label: "Flooded", tag: "info", icon: "water" },
  landslide_risk: { label: "Landslide risk", tag: "high", icon: "landslide" },
  disabled: { label: "Closed by you", tag: "", icon: "block" },
  unreachable: { label: "Unreachable", tag: "", icon: "wrong_location" },
};
/** OSM-unnamed candidate buildings get a findable description. */
export const niceName = (s: { name: string; place?: string }) =>
  /^(large building|unnamed|candidate)/i.test(s.name) && s.place ? `Large building ${s.place.startsWith("near ") ? s.place : "at " + s.place}` : s.name;
const pretty = (s: string) => s.replace(/^verified_/, "verified ").replace(/_/g, " ").replace(/^likely /, "likely ") + (s.startsWith("verified_") ? " (field photo)" : " (proxy)");

function Metric({ label, value, tip, alert, icon, wide, sub }: { label: string; value: string; tip: string; alert?: boolean; icon: string; wide?: boolean; sub?: string }) {
  return (
    <div className={`metric ${alert ? "alert" : ""} ${wide ? "wide" : ""}`}>
      <span className="l"><Icon name={icon} /> {label} <HelpTip text={tip} /></span>
      <span className="v">{value}</span>
      {sub && <span className="body-s muted">{sub}</span>}
    </div>
  );
}

function Chart({ data, unit, title, color, start }: { data: { h: number; v: number }[]; unit: string; title: string; color: string; start?: string | null }) {
  return (
    <figure style={{ margin: 0 }}>
      <figcaption className="label-m muted" style={{ marginBottom: 4 }}>{title}</figcaption>
      <ResponsiveContainer width="100%" height={120}>
        <AreaChart data={data} margin={{ top: 6, right: 8, bottom: 2, left: -12 }}>
          <defs><linearGradient id={`g-${title.replace(/\W+/g, "-")}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={color} stopOpacity={0.35} /><stop offset="1" stopColor={color} stopOpacity={0.02} /></linearGradient></defs>
          <CartesianGrid vertical={false} stroke="#9aa0a6" strokeOpacity={0.25} />
          <XAxis dataKey="h" tick={{ fontSize: 11, fill: "#80868b" }} tickLine={false} axisLine={false} tickFormatter={(h) => clockAt(start, h) ?? `h${h}`} />
          <YAxis tick={{ fontSize: 11, fill: "#80868b" }} tickLine={false} axisLine={false} width={44} />
          <Tooltip formatter={(v) => [`${v} ${unit}`, title]} labelFormatter={(h) => (clockAt(start, Number(h)) ? `${clockAt(start, Number(h))} (hour ${h})` : `Hour ${h}`)}
            contentStyle={{ borderRadius: 8, border: 0, boxShadow: "0 1px 3px rgba(0,0,0,.3)", fontFamily: "Google Sans" }} />
          <Area type="monotone" dataKey="v" stroke={color} strokeWidth={2} fill={`url(#g-${title.replace(/\W+/g, "-")})`} isAnimationActive animationDuration={450} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </figure>
  );
}

export default function Results({ run, hour, onFly, previous }: { run: RunResult; hour: number; onFly: (lon: number, lat: number) => void; previous?: RunResult | null }) {
  const [tab, setTab] = useState<"shelters" | "routes" | "bridges" | "buildings" | "drains">(run.drains?.length ? "drains" : "shelters");
  const e = run.exposure;
  const H = run.rain_series_mm_h.length;
  const peak = Math.max(0, ...e.exposed_pop_by_hour);
  const lsPeak = Math.max(0, ...e.landslide_exposed_pop_by_hour);
  const NOT_OPEN = ["construction", "closed", "disused"];
  const closing = run.bridges.filter((b) => b.first_closed_hour != null && !NOT_OPEN.includes(b.reason ?? ""));  // closed by the storm
  const notOpen = run.bridges.filter((b) => NOT_OPEN.includes(b.reason ?? "")).length;
  const first = closing[0];
  const crit = (e.buildings_by_risk.critical ?? 0) + (e.buildings_by_risk.high ?? 0);
  const usable = run.shelters.filter((s) => s.status === "usable").length;
  const triage = run.triage.filter((t) => t.risk_class !== "low").slice(0, 10);
  const trig = run.methods?.landslide_trigger_hours as number[] | undefined;
  const delta = (a: number, b: number) => (b === a ? "no change vs previous run" : `${b > a ? "+" : "−"}${nf(Math.abs(b - a))} vs previous run`);
  const rng = (r?: number[]) => (r && r.length === 2 && r[0] !== r[1] ? `range ${nf(roundPeople(r[0]))}–${nf(roundPeople(r[1]))}` : "");
  const bd = run.demand_breakdown ?? {};
  const shName = (id: string) => { const s = run.shelters.find((x) => x.id === id); return s ? niceName(s) : id; };
  const atH = (h: number) => clockAt(run.start_local, h) ?? `hour ${h}`;
  const why = (r: string | null) => (r ? ` · ${REASON[r] ?? r}` : "");

  return (
    <section className="stack" aria-label="Results">
      <div className="stack-s">
        <span className="label-m muted">{run.rain_label}{run.start_local ? "" : " · hypothetical rain, hours after it starts"}</span>
        <p className="body-l">
          About <b>{nf(roundPeople(run.people_to_evacuate))}</b> people need to move{run.evac_window_h ? <>, <b>{before(run.start_local, run.evac_window_h)}</b></> : null};
          {run.capacity_gap_people > 0 ? <> about <b style={{ color: "var(--error)" }}>{nf(roundPeople(run.capacity_gap_people))}</b> have no reachable shelter place</> : <> all can reach one of {usable} shelters</>}.
          {first ? <> The first bridge closes at {clockAt(run.start_local, first.first_closed_hour!) ?? <>hour <b>{first.first_closed_hour}</b></>}.</> : null}
        </p>
        {(bd.flood || bd.landslide) ? <span className="body-s muted">Why they move: {nf(bd.flood ?? 0)} flood water · {nf(bd.landslide ?? 0)} landslide-trigger slopes{bd.both ? ` · ${nf(bd.both)} both` : ""}</span> : null}
      </div>

      <div className="metrics">
        <Metric icon="water" label="In flood water (peak)" value={`≈ ${nf(roundPeople(peak))}`} sub={previous ? delta(Math.max(0, ...previous.exposure.exposed_pop_by_hour), peak) : undefined}
          tip="Estimated residents where water is at least 5 cm deep, at the worst hour." />
        <Metric icon="landslide" label="On landslide-trigger slopes" value={`≈ ${nf(roundPeople(lsPeak))}`}
          tip={trig && trig.length ? `People on class 4–5 slopes in hours when rain exceeds the trigger threshold (hours ${trig.join(", ")}).` : "Rain stays below the landslide trigger threshold in this scenario, so no one is counted."} />
        <Metric icon="directions_walk" label="Need to move" value={`≈ ${nf(roundPeople(run.people_to_evacuate))}`}
          sub={[rng(run.demand_range), previous ? delta(previous.people_to_evacuate, run.people_to_evacuate) : ""].filter(Boolean).join(" · ")}
          tip="People in buildings or cells that flood, or that reach landslide class 5 above the rain threshold." />
        <Metric icon="no_accounts" label="No shelter place" value={`≈ ${nf(roundPeople(run.capacity_gap_people))}`}
          sub={[rng(run.gap_range), previous ? delta(previous.capacity_gap_people, run.capacity_gap_people) : ""].filter(Boolean).join(" · ")}
          alert={run.capacity_gap_people > 0} tip="People who need to move but have no reachable shelter place within the travel limit." />
        <Metric icon="home_work" label="High-risk buildings" value={nf(crit)} tip="Buildings whose estimated risk (water depth damage curve, structure proxy, stream proximity, landslide) is high or critical." />
        <Metric icon="pin_drop" label="Bridges closing" value={`${closing.length} / ${run.bridges.length}`} sub={notOpen ? `+ ${notOpen} not open (OSM)` : undefined}
          tip={first ? `First: ${first.name} at hour ${first.first_closed_hour} (${REASON[first.reason ?? ""] ?? first.reason}).` : "No bridge closes in this scenario."} />
      </div>

      <nav className="next-steps" aria-label="Next steps">
        <Link className="btn btn-tonal small sl" to={`/area/${run.aoi_id}/run/${run.run_id}/advisory`}><Icon name="assignment" /> Read the brief</Link>
        <Link className="btn btn-text small sl" to={`/area/${run.aoi_id}/3d?run=${run.run_id}`}><Icon name="view_in_ar" /> Watch in 3D</Link>
        <Link className="btn btn-text small sl" to={`/area/${run.aoi_id}/drill?run=${run.run_id}`}><Icon name="sports_score" /> Rehearse (drill)</Link>
        <Link className="btn btn-text small sl" to={`/projects?area=${run.aoi_id}`}><Icon name="folder_open" /> Save &amp; compare</Link>
      </nav>

      <ModelCheck run={run} />

      <div className="stack-s">
        <Chart title="Flooded area" unit="km²" color="#1a73e8" start={run.start_local} data={run.flooded_area_km2_by_hour.map((v, i) => ({ h: i + 1, v }))} />
        <Chart title="People in flood water" unit="people" color="#08519c" start={run.start_local} data={e.exposed_pop_by_hour.map((v, i) => ({ h: i + 1, v }))} />
        <p className="body-s muted">Showing {clockAt(run.start_local, hour) ? `${clockAt(run.start_local, hour)} (hour ${hour} of ${H})` : `hour ${hour} of ${H}`}. Ranges show the effect of flood depth ±30% and population ±20%. Water never recedes within a scenario (worst-case envelope), which over-estimates on purpose.</p>
      </div>

      <div className="card outlined" style={{ padding: 0 }}>
        <Tabs value={tab} onChange={setTab} tabs={[
          { value: "shelters", label: "Shelters" }, { value: "routes", label: "Routes", badge: run.routes.filter((r) => r.use_now_gone_soon).length || undefined },
          ...(run.drains?.length ? [{ value: "drains" as const, label: "Drains" }] : [{ value: "bridges" as const, label: "Bridges" }]),
          { value: "buildings", label: "Buildings" },
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
                      <span className="t" style={{ display: "block", fontSize: 14 }}>{niceName(s).length > 40 ? niceName(s).slice(0, 40) + "…" : niceName(s)}</span>
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
              <thead><tr><th>To</th><th className="r">People</th><th className="r">ETA</th><th>Open until</th></tr></thead>
              <tbody>{run.routes.slice(0, 15).map((r, i) => (
                <tr key={i} className={r.from_lon != null ? "clickable" : ""} onClick={() => r.from_lon != null && onFly(r.from_lon, r.from_lat!)}>
                  <td><b>{shName(r.to_shelter)}</b>{r.place && <span className="body-s muted" style={{ display: "block" }}>from {r.place}</span>}{r.length_km != null && <span className="body-s muted"> · {r.length_km} km</span>}</td>
                  <td className="r">{nf(r.people)}</td>
                  <td className="r" title={r.access_min ? `includes ${r.access_min} min walk to the road network` : undefined}>{r.eta_min} min</td>
                  <td>{r.passable_until_h == null ? <span className="body-s muted">all scenario</span>
                    : routeClosed(r.passable_until_h, hour) ? <span className="tag crit" title="A road on this route is closed at the selected hour">closed since {atH(r.passable_until_h)}</span>
                      : <>{atH(r.passable_until_h)} {r.use_now_gone_soon && <span className="tag high" title="Closes soon after the evacuation starts">use now</span>}</>}</td>
                </tr>
              ))}</tbody>
            </table>
          ) : <p className="body-m muted" style={{ padding: 16 }}>No routes: nobody needs to move, or no shelter is reachable.</p>)}
          {tab === "bridges" && (
            <div className="list">
              {run.bridges.slice(0, 20).map((b) => (
                <div key={b.id} className="li dense clickable sl" onClick={() => onFly(b.lon, b.lat)} role="button" tabIndex={0}>
                  <span className="label-l" style={{ width: 28, color: "var(--primary)" }}>{b.id}</span>
                  <span className="txt"><span className="t" style={{ fontSize: 14 }}>{b.name}</span>{deckLine(b) && <span className="s">{deckLine(b)}</span>}</span>
                  {b.first_closed_hour == null ? <span className="tag">stays open</span>
                    : b.first_closed_hour <= hour
                      ? <span className="tag crit"><img className="mk" src={markerUrl("bridgeClosed")} alt="" width={14} height={14} />closed since {atH(b.first_closed_hour)}{why(b.reason)}</span>
                      : <span className="tag high"><img className="mk" src={markerUrl("bridgeLater")} alt="" width={14} height={14} />closes at {atH(b.first_closed_hour)}{why(b.reason)}</span>}
                </div>
              ))}
              {!run.bridges.length && <p className="body-m muted" style={{ padding: 16 }}>No bridges mapped in OpenStreetMap here.</p>}
            </div>
          )}
          {tab === "drains" && (
            <div className="list">
              <p className="body-s muted" style={{ padding: "4px 16px 8px" }}>Inspect and clear before the monsoon, highest priority first (flow, ponding, people within 300 m).</p>
              {(run.drains ?? []).map((d) => (
                <div key={d.id} className="li dense clickable sl" onClick={() => onFly(d.lon, d.lat)} role="button" tabIndex={0}>
                  <span className="label-l" style={{ width: 28, color: "var(--primary)" }}>{d.id}</span>
                  <span className="txt"><span className="t" style={{ fontSize: 14 }}>{d.name || d.type}</span>
                    <span className="s" style={{ display: "block" }}>{d.type} · {nf(d.exposed_people_300m)} exposed within 300 m{d.photo_condition ? ` · photo: ${d.photo_condition.replace("_", " ")}` : ""}</span></span>
                  <span className={`tag ${d.priority >= 0.6 ? "crit" : d.priority >= 0.4 ? "high" : ""}`}>{d.priority.toFixed(2)}</span>
                </div>
              ))}
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
