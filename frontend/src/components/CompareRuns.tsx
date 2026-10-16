import { useEffect, useState } from "react";
import { getAoiRuns } from "../api/client";
import { before, roundPeople } from "../time";
import type { RunSummary } from "../types/api";
import { Button, Icon, nf } from "./m3";

const CHANGE_LABEL: Record<string, string> = {
  disabled_shelter_ids: "shelters closed", extra_shelters: "shelters added", blocked_polygons: "roads blocked", visitors: "visitors",
  travel_mode: "travel", evac_start_hour: "evacuation starts at hour",
};
const changes = (c: Record<string, unknown>) => Object.entries(c).map(([k, v]) => `${CHANGE_LABEL[k] ?? k}: ${Array.isArray(v) ? v.length : String(v)}`).join(" · ");

/** Side-by-side scenarios for one area ("do nothing" vs "open two schools" vs "close the bypass"). */
export default function CompareRuns({ aoiId, currentId, onOpen }: { aoiId: string; currentId: string | null; onOpen: (runId: string) => void }) {
  const [rows, setRows] = useState<RunSummary[] | null>(null);
  const [pick, setPick] = useState<string[]>([]);
  useEffect(() => {
    getAoiRuns(aoiId).then((r) => { setRows(r); setPick(r.slice(0, 3).map((x) => x.run_id)); }).catch(() => setRows([]));
  }, [aoiId, currentId]);
  if (!rows) return <div className="shimmer" style={{ height: 160 }} />;
  if (!rows.length) return <p className="body-m muted">No scenarios yet. Run one on the Scenario tab.</p>;
  const cols = rows.filter((r) => pick.includes(r.run_id)).slice(0, 3);
  const base = cols[cols.length - 1];
  const diff = (a: number, b: number) => (a === b ? "" : ` (${a > b ? "+" : "−"}${nf(Math.abs(a - b))})`);
  const line = (label: string, f: (r: RunSummary) => string) => (
    <tr><th>{label}</th>{cols.map((r) => <td key={r.run_id} className="r">{f(r)}</td>)}</tr>
  );
  return (
    <div className="stack">
      <p className="body-s muted">Pick up to three scenarios. Differences are against the oldest one shown (right).</p>
      <div className="list">
        {rows.map((r) => (
          <label key={r.run_id} className="layer-row" style={{ cursor: "pointer" }}>
            <input type="checkbox" checked={pick.includes(r.run_id)} onChange={() => setPick((p) => p.includes(r.run_id) ? p.filter((x) => x !== r.run_id) : [...p, r.run_id].slice(-3))} />
            <span className="txt"><span className="t" style={{ fontSize: 14 }}>{r.rain_label}</span>
              <span className="s">{new Date(r.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}{Object.keys(r.changes).length ? ` · ${changes(r.changes)}` : ""}{r.run_id === currentId ? " · on the map" : ""}</span></span>
          </label>
        ))}
      </div>
      {cols.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table className="tbl compare">
            <thead><tr><th />{cols.map((r, i) => <th key={r.run_id} className="r">{String.fromCharCode(65 + i)}</th>)}</tr></thead>
            <tbody>
              {line("Need to move", (r) => `≈ ${nf(roundPeople(r.people_to_evacuate))}${r === base ? "" : diff(r.people_to_evacuate, base.people_to_evacuate)}`)}
              {line("No shelter place", (r) => `≈ ${nf(roundPeople(r.capacity_gap_people))}${r === base ? "" : diff(r.capacity_gap_people, base.capacity_gap_people)}`)}
              {line("Move before", (r) => before(r.start_local, r.evac_window_h) || "–")}
              {line("Bridges closing", (r) => `${r.bridges_closing} / ${r.bridges_total}`)}
              {line("In flood water", (r) => `≈ ${nf(roundPeople(r.flood_peak))}`)}
              {line("Flooded area", (r) => `${r.flooded_km2} km²`)}
              {line("Shelters used", (r) => String(r.shelters_used))}
              <tr><th />{cols.map((r) => <td key={r.run_id} className="r">
                <Button variant="text" size="small" icon={r.run_id === currentId ? "check" : "map"} disabled={r.run_id === currentId} onClick={() => onOpen(r.run_id)}>{r.run_id === currentId ? "Shown" : "Show"}</Button></td>)}</tr>
            </tbody>
          </table>
          <div className="body-s muted">{cols.map((r, i) => <div key={r.run_id}><b>{String.fromCharCode(65 + i)}</b>: {r.rain_label}{Object.keys(r.changes).length ? ` · ${changes(r.changes)}` : ""}</div>)}</div>
        </div>
      )}
      <div className="row body-s muted"><Icon name="info" className="sm" /> Figures are rounded; see each run's Results for ranges.</div>
    </div>
  );
}
