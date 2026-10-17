// Second opinion: the run's HAND flood map (what the brief uses) next to the independent 2D shallow-water model run
// on the same storm. Agreement is shown as the critical success index of the wet areas.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiUrl } from "../api/client";
import { roundPeople } from "../time";
import type { RunResult } from "../types/api";
import { HelpTip, Icon, Linear, nf } from "./m3";

type Flow = { state: string; progress?: number; flooded_km2?: number; people?: { in_water: number; knee_deep: number };
  compare_hand?: { hand_km2: number; flow_km2: number; both_km2: number; csi: number | null; share_of_hand_also_wet: number } };

export default function ModelCheck({ run }: { run: RunResult }) {
  const [f, setF] = useState<Flow | null>(null);
  useEffect(() => {
    let alive = true, t: number | undefined;
    const poll = () => fetch(apiUrl(`/api/runs/${run.run_id}/flow`)).then((r) => r.json()).then((x: Flow) => {
      if (!alive) return;
      setF(x);
      if (x.state === "queued" || x.state === "running") t = window.setTimeout(poll, 5000);
    }).catch(() => undefined);
    poll();
    return () => { alive = false; window.clearTimeout(t); };
  }, [run.run_id]);
  if (!f || f.state === "none" || f.state === "failed" || f.state === "stale") return null;
  const handPeople = Math.max(0, ...run.exposure.exposed_pop_by_hour);
  if (f.state !== "ready") return (
    <div className="card tonal stack-s"><span className="title-s row" style={{ gap: 6 }}><Icon name="fact_check" className="sm" />Cross-check with the 2D water model</span>
      <Linear value={f.progress ?? 0} /><span className="body-s muted">Running the detailed water-flow model on the same storm…</span></div>
  );
  const c = f.compare_hand;
  const agree = c?.csi == null ? null : c.csi;
  const verdict = agree == null ? "" : agree >= 0.5 ? "The two models broadly agree." : agree >= 0.25 ? "The two models partly agree: treat the extent as uncertain." : "The two models disagree on where water goes: check the 3D view before acting on the flood extent.";
  return (
    <div className="card outlined stack-s model-check">
      <span className="title-s row" style={{ gap: 6 }}><Icon name="fact_check" className="sm" />Cross-check with the 2D water model
        <HelpTip text="The brief uses the fast HAND flood map (height above the nearest stream). The 2D model solves the shallow-water equations on the same storm, cell by cell, so it also sees ponding, overland flow and backwater. Agreement = shared wet area ÷ wet area of either (critical success index)." /></span>
      <table className="tbl"><thead><tr><th /><th className="r">Flood map (brief)</th><th className="r">2D model</th></tr></thead>
        <tbody>
          <tr><th>Flooded area</th><td className="r">{c?.hand_km2?.toFixed(2) ?? "–"} km²</td><td className="r">{(c?.flow_km2 ?? f.flooded_km2)?.toFixed(2)} km²</td></tr>
          <tr><th>People in flood water</th><td className="r">≈ {nf(roundPeople(handPeople))}</td><td className="r">≈ {nf(roundPeople(f.people?.in_water ?? 0))}</td></tr>
          {agree != null && <tr><th>Agreement (wet area)</th><td className="r" colSpan={2}>{Math.round(agree * 100)}%</td></tr>}
        </tbody></table>
      {verdict && <p className="body-s" style={{ margin: 0 }}>{verdict}</p>}
      <Link className="btn btn-text small sl" style={{ alignSelf: "flex-start" }} to={`/area/${run.aoi_id}/3d?run=${run.run_id}`}><Icon name="view_in_ar" /> See the water move in 3D</Link>
    </div>
  );
}
