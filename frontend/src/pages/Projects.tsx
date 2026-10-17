// Projects: every prepared area and, inside each, every saved scenario run (an experiment). Runs can be named,
// annotated, starred, compared side by side, made the area's default (what Brief, Map and 3D open) or archived.
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { deleteAoi, deleteRun, getAoiRuns, getProjects, setRunMeta } from "../api/client";
import { Button, Dialog, Icon, IconButton, nf, useSnackbar } from "../components/m3";
import { bboxKm } from "../components/DrawControl";
import type { ProjectArea, RunSummary } from "../types/api";
import "./projects.css";

const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "");
const runName = (r: RunSummary) => r.title || r.rain_label;
const CHANGE: Record<string, string> = {
  disabled_shelter_ids: "shelters closed", extra_shelters: "shelters added", blocked_polygons: "roads blocked", visitors: "visitors",
  travel_mode: "travel", evac_start_hour: "evacuation from hour",
};
function setup(r: RunSummary): string {
  const bits = [`${nf(r.rain_total_mm)} mm in ${r.duration_h} h`];
  if (r.river_offset_m) bits.push(`river ${r.river_offset_m > 0 ? "+" : ""}${r.river_offset_m} m`);
  for (const [k, v] of Object.entries(r.changes ?? {})) bits.push(`${CHANGE[k] ?? k}: ${Array.isArray(v) ? v.length : String(v)}`);
  return bits.join(" · ");
}

export default function Projects() {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const snack = useSnackbar();
  const [areas, setAreas] = useState<ProjectArea[] | null>(null);
  const [loadErr, setLoadErr] = useState("");
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [pick, setPick] = useState<string[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [openNotes, setOpenNotes] = useState<string | null>(null);
  // permanent deletion, always behind a confirmation (archive stays the reversible option)
  const [confirm, setConfirm] = useState<{ kind: "run"; run: RunSummary } | { kind: "area" } | null>(null);
  const [deleting, setDeleting] = useState(false);
  async function doDelete() {
    if (!confirm) return;
    setDeleting(true);
    try {
      if (confirm.kind === "run") {
        await deleteRun(confirm.run.run_id);
        setRuns((xs) => xs?.filter((x) => x.run_id !== confirm.run.run_id) ?? xs);
        snack("Run deleted");
        load();
        if (confirm.run.is_current && sel) getAoiRuns(sel, 100, showArchived).then(setRuns).catch(() => undefined);
      } else if (area) {
        const r = await deleteAoi(area.aoi_id);
        snack(`Deleted ${area.name || "the area"} and ${r.runs} run${r.runs === 1 ? "" : "s"}`);
        setParams({}, { replace: true });
        load();
      }
      setConfirm(null);
    } catch (e) {
      snack("Could not delete: " + String((e as Error).message));
    } finally { setDeleting(false); }
  }
  const sel = params.get("area");
  const area = areas?.find((a) => a.aoi_id === sel) ?? null;

  const load = () => { setLoadErr(""); getProjects().then(setAreas).catch((e) => setLoadErr(String((e as Error).message))); };
  useEffect(load, []);
  useEffect(() => {  // open the most recently used area when none is chosen
    if (areas && !sel) { const a = areas.find((x) => !x.archived && x.runs > 0) ?? areas[0]; if (a) setParams({ area: a.aoi_id }, { replace: true }); }
  }, [areas, sel, setParams]);
  useEffect(() => {
    if (!sel) return;
    setRuns(null); setPick([]);
    getAoiRuns(sel, 100, showArchived).then(setRuns).catch(() => setRuns([]));
  }, [sel, showArchived]);

  const shown = useMemo(() => {
    if (!runs) return null;
    return [...runs].sort((a, b) => Number(!!b.starred) - Number(!!a.starred) || String(b.created_at).localeCompare(String(a.created_at)));
  }, [runs]);

  async function patch(r: RunSummary, meta: Parameters<typeof setRunMeta>[1], msg?: string) {
    try {
      await setRunMeta(r.run_id, meta);
      setRuns((xs) => {
        if (!xs) return xs;
        let out = xs.map((x) => (x.run_id === r.run_id ? { ...x, ...meta, title: meta.title !== undefined ? meta.title || null : x.title } : x));
        if (meta.make_current) out = out.map((x) => ({ ...x, is_current: x.run_id === r.run_id }));
        if (meta.archived !== undefined) out = out.filter((x) => x.run_id !== r.run_id);
        return out;
      });
      if (meta.starred !== undefined) setAreas((as) => as?.map((a) => (a.aoi_id === sel ? { ...a, starred: a.starred + (meta.starred ? 1 : -1) } : a)) ?? as);
      if (msg) snack(msg, meta.archived ? { label: "Undo", onClick: () => setRunMeta(r.run_id, { archived: false }).then(() => getAoiRuns(sel!, 100, showArchived).then(setRuns)) } : undefined);
    } catch (e) { snack("Could not save: " + String((e as Error).message)); }
  }
  const copyLink = (r: RunSummary) => {
    const url = `${window.location.origin}/area/${sel}?run=${r.run_id}`;
    navigator.clipboard?.writeText(url).then(() => snack("Link copied. It opens this run on the map.")).catch(() => snack(url));
  };

  const cmp = (shown ?? []).filter((r) => pick.includes(r.run_id));

  return (
    <div className="doc-page">
      <div className="doc projects">
        <div className="doc-head row">
          <div className="grow">
            <h1 className="headline-s" style={{ margin: 0 }}>Projects</h1>
            <p className="body-m muted" style={{ margin: "4px 0 0" }}>Every area you prepare and every scenario you run is saved here. Name runs, add notes, star the ones to show others, and compare up to three side by side.</p>
          </div>
          <Button icon="add_location_alt" onClick={() => nav("/")}>New area</Button>
        </div>

        {loadErr && <div className="notice error"><Icon name="error" /><span className="grow">Projects could not be loaded ({loadErr}).</span><Button variant="text" onClick={load}>Try again</Button></div>}
        {areas && !areas.length && (
          <div className="card outlined empty">
            <Icon name="map" className="lg" />
            <p className="title-m">No areas yet</p>
            <p className="body-m muted">Draw a box on the map to prepare an area (about 2 minutes), then run a scenario.</p>
            <Button icon="draw" onClick={() => nav("/")}>Draw an area</Button>
          </div>
        )}

        <div className="pj-grid">
          <nav className="pj-areas" aria-label="Areas">
            {!areas && !loadErr && [0, 1, 2].map((i) => <div key={i} className="shimmer" style={{ height: 64, borderRadius: 12 }} />)}
            {areas?.map((a) => {
              const km = bboxKm(a.bbox);
              return (
                <button key={a.aoi_id} className={`pj-area sl ${a.aoi_id === sel ? "on" : ""} ${a.archived ? "dim" : ""}`} onClick={() => setParams({ area: a.aoi_id })}>
                  <span className={`avatar ${a.mode}`}><Icon name={a.mode === "urban" ? "location_city" : "landscape"} /></span>
                  <span className="txt">
                    <span className="t">{a.name || "Unnamed area"}</span>
                    <span className="s">{a.mode === "urban" ? "Urban" : "River & hills"} · {km[0].toFixed(0)} × {km[1].toFixed(0)} km · {a.runs} run{a.runs === 1 ? "" : "s"}{a.starred ? ` · ${a.starred} ★` : ""}{a.archived ? " · archived" : ""}</span>
                  </span>
                </button>
              );
            })}
          </nav>

          <section className="pj-runs" aria-label="Runs">
            {area && (
              <>
                <div className="row pj-area-head">
                  <div className="grow">
                    <h2 className="title-l" style={{ margin: 0 }}>{area.name || "Unnamed area"}</h2>
                    <p className="body-s muted" style={{ margin: "2px 0 0" }}>{area.last_run_at ? `Last run ${when(area.last_run_at)}` : "No runs yet"}{area.state !== "ready" ? ` · data ${area.state}` : ""}</p>
                  </div>
                  <Link className="btn btn-tonal sl" to={`/area/${area.aoi_id}`}><Icon name="add" /> New run</Link>
                  <IconButton icon="delete" label="Delete this area and all its runs" onClick={() => setConfirm({ kind: "area" })} />
                </div>

                {pick.length > 0 && (
                  <div className="card tonal pj-compare">
                    <div className="row"><span className="title-s grow">Comparing {cmp.length} run{cmp.length === 1 ? "" : "s"}</span><Button variant="text" onClick={() => setPick([])}>Clear</Button></div>
                    <div className="pj-table-wrap">
                      <table className="tbl">
                        <thead><tr><th />{cmp.map((r) => <th key={r.run_id} className="r">{runName(r)}</th>)}</tr></thead>
                        <tbody>
                          <tr><th>Rain</th>{cmp.map((r) => <td key={r.run_id} className="r">{nf(r.rain_total_mm)} mm / {r.duration_h} h</td>)}</tr>
                          <tr><th>People to move</th>{cmp.map((r) => <td key={r.run_id} className="r">{nf(r.people_to_evacuate)}</td>)}</tr>
                          <tr><th>Without a shelter place</th>{cmp.map((r) => <td key={r.run_id} className={`r ${r.capacity_gap_people > 0 ? "bad" : ""}`}>{nf(r.capacity_gap_people)}</td>)}</tr>
                          <tr><th>People in flood water (peak)</th>{cmp.map((r) => <td key={r.run_id} className="r">{nf(r.flood_peak)}</td>)}</tr>
                          <tr><th>Flooded area</th>{cmp.map((r) => <td key={r.run_id} className="r">{r.flooded_km2?.toFixed(2)} km²</td>)}</tr>
                          <tr><th>Bridges closing</th>{cmp.map((r) => <td key={r.run_id} className="r">{r.bridges_closing} of {r.bridges_total}</td>)}</tr>
                          <tr><th>Shelters used</th>{cmp.map((r) => <td key={r.run_id} className="r">{r.shelters_used}</td>)}</tr>
                          <tr><th>Move people before</th>{cmp.map((r) => <td key={r.run_id} className="r">{r.evac_window_h ? `hour ${r.evac_window_h}` : "–"}</td>)}</tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {!shown && [0, 1, 2].map((i) => <div key={i} className="shimmer" style={{ height: 96, borderRadius: 12 }} />)}
                {shown && !shown.length && (
                  <div className="card outlined empty">
                    <p className="title-s">{showArchived ? "No archived runs" : "No runs in this area yet"}</p>
                    {!showArchived && <p className="body-m muted">Open the map, choose the rain, and press Run scenario. Each run is saved here automatically.</p>}
                    {!showArchived && <Link className="btn btn-filled sl" to={`/area/${area.aoi_id}`}><Icon name="play_arrow" /> Open the map</Link>}
                  </div>
                )}
                {shown?.map((r) => (
                  <article key={r.run_id} className={`pj-run card outlined ${r.is_current ? "current" : ""}`}>
                    <div className="row nowrap pj-run-top">
                      <input type="checkbox" aria-label="Compare" title="Compare (up to three)" checked={pick.includes(r.run_id)}
                        onChange={() => setPick((p) => (p.includes(r.run_id) ? p.filter((x) => x !== r.run_id) : [...p, r.run_id].slice(-3)))} />
                      <IconButton icon="star" fill={!!r.starred} label={r.starred ? "Unstar" : "Star (pinned to the top)"} small on={!!r.starred}
                        onClick={() => patch(r, { starred: !r.starred })} />
                      <div className="grow" style={{ minWidth: 0 }}>
                        {editing === r.run_id ? (
                          <form className="row nowrap" onSubmit={(e) => { e.preventDefault(); setEditing(null); patch(r, { title: draft }, "Name saved"); }}>
                            <input className="pj-input" autoFocus value={draft} maxLength={120} onChange={(e) => setDraft(e.target.value)} placeholder={r.rain_label}
                              onKeyDown={(e) => e.key === "Escape" && setEditing(null)} aria-label="Run name" />
                            <Button size="small" type="submit">Save</Button>
                          </form>
                        ) : (
                          <button className="pj-title sl" title="Rename" onClick={() => { setEditing(r.run_id); setDraft(r.title ?? ""); }}>
                            <span>{runName(r)}</span><Icon name="edit" className="sm" />
                          </button>
                        )}
                        <div className="body-s muted">{when(r.created_at)} · {setup(r)}{r.title ? ` · ${r.rain_label}` : ""}</div>
                      </div>
                      {r.is_current && <span className="tag info" title="Brief, Map and 3D open this run">Default</span>}
                    </div>
                    <div className="pj-metrics">
                      <span><b>{nf(r.people_to_evacuate)}</b> to move</span>
                      <span className={r.capacity_gap_people > 0 ? "bad" : ""}><b>{nf(r.capacity_gap_people)}</b> without a place</span>
                      <span><b>{r.bridges_closing}</b> of {r.bridges_total} bridges close</span>
                      <span><b>{r.flooded_km2?.toFixed(2)}</b> km² flooded</span>
                    </div>
                    {openNotes === r.run_id ? (
                      <textarea className="pj-notes" defaultValue={r.notes ?? ""} placeholder="What did you change, and what did you learn? (visible to everyone with the link)"
                        autoFocus rows={3} onBlur={(e) => { setOpenNotes(null); if ((e.target.value || "") !== (r.notes || "")) patch(r, { notes: e.target.value }, "Notes saved"); }} />
                    ) : r.notes ? <p className="body-s pj-note" onClick={() => setOpenNotes(r.run_id)}>{r.notes}</p> : null}
                    <div className="row pj-actions">
                      <Link className="btn btn-text small sl" to={`/area/${sel}?run=${r.run_id}`}><Icon name="map" /> Map</Link>
                      <Link className="btn btn-text small sl" to={`/area/${sel}/run/${r.run_id}/advisory`}><Icon name="assignment" /> Brief</Link>
                      <Link className="btn btn-text small sl" to={`/area/${sel}/3d?run=${r.run_id}`}><Icon name="view_in_ar" /> 3D</Link>
                      <span className="grow" />
                      <IconButton icon="sticky_note_2" label={r.notes ? "Edit notes" : "Add notes"} small onClick={() => setOpenNotes(r.run_id)} />
                      <IconButton icon="link" label="Copy link" small onClick={() => copyLink(r)} />
                      {!r.is_current && !r.archived && <IconButton icon="push_pin" label="Make default (Brief, Map and 3D open this run)" small onClick={() => patch(r, { make_current: true }, "Brief, Map and 3D now open this run")} />}
                      {!r.is_current && <IconButton icon={r.archived ? "unarchive" : "archive"} label={r.archived ? "Restore" : "Archive"} small
                        onClick={() => patch(r, { archived: !r.archived }, r.archived ? "Run restored" : "Run archived")} />}
                      <IconButton icon="delete" label="Delete run" small onClick={() => setConfirm({ kind: "run", run: r })} />
                    </div>
                  </article>
                ))}
                <button className="btn btn-text sl" style={{ alignSelf: "flex-start" }} onClick={() => setShowArchived(!showArchived)}>
                  <Icon name={showArchived ? "arrow_back" : "inventory_2"} /> {showArchived ? "Back to saved runs" : "Show archived runs"}
                </button>
              </>
            )}
          </section>
        </div>
      </div>
      <Dialog open={!!confirm} icon="delete" onClose={() => !deleting && setConfirm(null)}
        title={confirm?.kind === "area" ? `Delete ${area?.name || "this area"}?` : "Delete this run?"}
        actions={<>
          <Button variant="text" disabled={deleting} onClick={() => setConfirm(null)}>Cancel</Button>
          <Button variant="danger" disabled={deleting} onClick={doDelete}>{deleting ? "Deleting…" : "Delete permanently"}</Button>
        </>}>
        {confirm?.kind === "area" ? (
          <p className="body-m">This removes the area's prepared data and <b>all {area?.runs ?? 0} run{area?.runs === 1 ? "" : "s"}</b>, with their briefs, 3D models, alerts and drills. It cannot be undone. To hide it instead, archive it from the area list.</p>
        ) : confirm?.kind === "run" ? (
          <p className="body-m"><b>{confirm.run.title || confirm.run.rain_label || "This run"}</b> and its brief, 3D model, alert and drills will be removed. It cannot be undone{confirm.run.is_current ? "; the newest remaining run becomes the default" : ""}. Archive keeps it but hides it.</p>
        ) : null}
      </Dialog>
    </div>
  );
}
