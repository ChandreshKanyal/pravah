// Click a shelter or an evacuation route (2D map or 3D): the checks behind the choice, from the run itself, and
// Gemini's plain-words explanation of them (backend agents/explain.py; nothing it says comes from elsewhere).
import { useEffect, useState } from "react";
import { explainChoice } from "../api/client";
import type { Explanation, RunResult, ShelterResult } from "../types/api";
import { clockAt } from "../time";
import { Icon, IconButton, nf } from "./m3";
import { niceName } from "./Results";

export type Choice = { kind: "shelter"; id: string } | { kind: "route"; key: string };

const KIND: Record<string, string> = {
  school: "School", college: "College", university: "University", community_centre: "Community centre", townhall: "Town hall",
  social_facility: "Social facility", place_of_worship: "Place of worship (large hall)", candidate_large_building: "Large building (unverified)",
  assembly_point: "Open assembly ground", user_added: "Added by you",
};
const FREEBOARD_M = 0.6, GUIDE_KM = 2.25;

type Row = { ok: boolean | null; icon?: string; text: string; sub?: string };

function shelterRows(s: ShelterResult, at: (h: number) => string): Row[] {
  const c = s.checks, out: Row[] = [];
  if (!c) return [{ ok: null, text: "Checks are available for runs made after 18 Oct; run the scenario again." }];
  out.push(c.peak_depth_m > 0 || c.wet_from_h
    ? { ok: false, text: `Flood water reaches it from ${at(c.wet_from_h ?? 1)}`, sub: `Up to ${c.peak_depth_m} m at the building` }
    : { ok: true, text: "Stays dry all scenario", sub: "No flood water on its own 30 m cell at any hour" });
  out.push(c.freeboard_m == null
    ? { ok: true, text: "No flood water on lower ground within 150 m" }
    : { ok: c.freeboard_m >= FREEBOARD_M, text: `${c.freeboard_m >= 0 ? c.freeboard_m.toFixed(1) + " m above" : Math.abs(c.freeboard_m).toFixed(1) + " m below"} the peak flood water nearby`,
        sub: `Nearest flood water about ${nf(c.nearest_water_m ?? 0)} m away · rule: at least ${FREEBOARD_M} m (IS 14264 plinth level)` });
  out.push(c.door_cut_h == null ? { ok: true, text: "Roads at the door stay open all scenario" }
    : { ok: false, text: `Every road at the door is closed from ${at(c.door_cut_h)}`, sub: "It can be cut off: people must arrive before then (ARC 4496: avoid isolated shelters)" });
  if (c.hand_m != null) out.push({ ok: c.hand_m >= 2 ? true : null, text: `${c.hand_m} m above the nearest stream or drain`, sub: "Height above drainage (MERIT Hydro)" });
  if (s.farthest_km != null) out.push({ ok: s.farthest_km <= GUIDE_KM, text: `Farthest home ${s.farthest_km} km away · slowest about ${s.slowest_min} min`, sub: `Planning aim: a shelter within ${GUIDE_KM} km (Odisha cyclone shelter plan)` });
  out.push({ ok: s.capacity_confidence === "low" ? null : true, text: `Room for ${nf(s.capacity)} people`,
    sub: `${s.area_m2 ? `${nf(Math.round(s.area_m2))} m² × ${s.floors ?? 1} floor${(s.floors ?? 1) > 1 ? "s" : ""}, ` : ""}60% usable at 3.5 m² a person (Sphere)${s.capacity_confidence === "low" ? " · size estimated, confirm" : ""}` });
  return out;
}

function routeRows(r: Record<string, any>, at: (h: number) => string): Row[] {
  const out: Row[] = [];
  out.push(r.passable_until_h == null ? { ok: true, text: "Stays open all scenario" }
    : { ok: (r.margin_h ?? 0) >= 1, text: `Open until ${at(r.passable_until_h)}`, sub: r.margin_h != null ? `${r.margin_h >= 0 ? `${r.margin_h} h to spare after arriving` : "closes before people arrive: leave earlier"}` : undefined });
  out.push({ ok: (r.max_water_m ?? 0) < 0.15, text: r.max_water_m ? `Deepest water on it at the start: ${r.max_water_m} m` : "Dry at the start of the evacuation", sub: "Roads deeper than the walking limit are left out" });
  if (r.via?.length) out.push({ ok: null, icon: "signpost", text: `Via ${r.via.join(", ")}`, sub: `${Math.round(100 * (r.main_road_share ?? 0))}% on main roads` });
  if (r.bridges_on_route) out.push({ ok: null, icon: "warning", text: `Crosses ${r.bridges_on_route} bridge${r.bridges_on_route > 1 ? "s" : ""}`, sub: "Bridges that close in this scenario are already avoided" });
  if (r.steep_m) out.push({ ok: null, icon: "landslide", text: `${nf(r.steep_m)} m next to steep ground` });
  out.push({ ok: (r.crowding ?? 0) < 0.6, text: (r.crowding ?? 0) >= 0.6 ? "Busy streets (markets, stations)" : "Not crowded", sub: "Crowding slows walking; ETA allows for it" });
  return out;
}

export default function ChoiceCard({ run, choice, routes, onClose, className = "" }: {
  run: RunResult; choice: Choice; routes?: Record<string, any>[]; onClose: () => void; className?: string;
}) {
  const [ex, setEx] = useState<Explanation | null>(null);
  const [failed, setFailed] = useState(false);
  const key = choice.kind === "shelter" ? choice.id : choice.key;
  useEffect(() => {
    let alive = true;
    setEx(null); setFailed(false);
    explainChoice(run.run_id, choice.kind, key).then((e) => alive && setEx(e)).catch(() => alive && setFailed(true));
    return () => { alive = false; };
  }, [run.run_id, choice.kind, key]);
  const at = (h: number) => { const c = clockAt(run.start_local, h); return c ? `${c} (hour ${h})` : `hour ${h}`; };
  const shelter = choice.kind === "shelter" ? run.shelters.find((s) => s.id === choice.id) : undefined;
  // the explanation's facts are the full route record; the map's copy shows meanwhile
  const route = choice.kind === "route" ? (ex?.facts?.route ?? routes?.find((r) => `${r.from_node}-${r.to_shelter}` === choice.key)) : undefined;
  const target = route ? run.shelters.find((s) => s.id === route.to_shelter) : undefined;
  if (choice.kind === "shelter" && !shelter) return null;

  const rows = shelter ? shelterRows(shelter, at) : route ? routeRows(route, at) : [];
  const used = shelter ? shelter.assigned > 0 : true;
  const status = shelter ? (shelter.status === "usable" ? (used ? `Sending ${nf(shelter.assigned)} people` : "Usable, not needed in this plan")
    : ({ flooded: "Not used: floods", disabled: "Closed by you", unreachable: "Not used: no open road" } as Record<string, string>)[shelter.status] ?? shelter.status) : "";
  return (
    <div className={`card elevated choice-card ${className}`} role="dialog" aria-label={shelter ? "Shelter details" : "Route details"}>
      <div className="cc-head">
        <Icon name={shelter ? (shelter.kind === "assembly_point" ? "groups" : "home_work") : "directions_walk"} className="cc-ic" />
        <div className="grow">
          <div className="title-m">{shelter ? `${shelter.id} · ${niceName(shelter)}` : `Route to ${target ? `${target.id} ${niceName(target)}` : route?.to_shelter ?? ""}`}</div>
          <div className="body-s muted">{shelter ? `${KIND[shelter.kind] ?? shelter.kind} · ${status}`
            : route ? `${nf(route.people)} people${route.place ? ` from ${route.place}` : ""} · ${route.eta_min} min · ${route.length_km} km` : "Loading…"}</div>
        </div>
        <IconButton icon="close" label="Close" onClick={onClose} />
      </div>

      <div className="cc-ai">
        <div className="cc-ai-h"><span className={`asst-spark ${ex || failed ? "" : "on"}`} aria-hidden="true">
          <svg viewBox="0 0 24 24" width="16" height="16"><defs><linearGradient id="ccspark" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#4285f4" /><stop offset=".55" stopColor="#9b72cb" /><stop offset="1" stopColor="#d96570" /></linearGradient></defs>
            <path fill="url(#ccspark)" d="M12 2c.6 4.8 4.4 9.4 10 10-5.6.6-9.4 5.2-10 10-.6-4.8-4.4-9.4-10-10 5.6-.6 9.4-5.2 10-10z" /></svg></span>
          {ex?.ai ? <b>{ex.ai.headline}</b> : failed || (ex && !ex.ai) ? <span className="muted">Gemini's explanation is unavailable; the checks below are the facts it uses.</span>
            : <span className="asst-shimmer">Gemini is explaining this choice…</span>}
        </div>
        {ex?.ai && (
          <>
            <ul className="cc-list">{ex.ai.reasons.map((t, i) => <li key={i}>{t}</li>)}</ul>
            {ex.ai.cautions.length > 0 && <><div className="label-m cc-sub">Check on the ground</div><ul className="cc-list warn">{ex.ai.cautions.map((t, i) => <li key={i}>{t}</li>)}</ul></>}
          </>
        )}
      </div>

      <div className="label-m cc-sub">{shelter ? "Checks in this scenario" : "Along the route"}</div>
      <ul className="cc-checks">
        {rows.map((r, i) => (
          <li key={i}>
            <Icon name={r.icon ?? (r.ok === true ? "check_circle" : r.ok === false ? "error" : "info")} className={`sm ${r.ok === true ? "ok" : r.ok === false ? "bad" : "neutral"}`} />
            <span><span className="t">{r.text}</span>{r.sub && <span className="s">{r.sub}</span>}</span>
          </li>
        ))}
      </ul>
      <p className="body-s muted cc-foot">Shelters are reachable in this scenario, never guaranteed safe. Decision-support draft for official review.</p>
    </div>
  );
}
