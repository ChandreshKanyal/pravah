import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMap } from "@vis.gl/react-google-maps";
import {
  advisoryVersion, advisoryVersions, getAdvisory, getAoiStatus, getRun, requestAdvisory, reviewAdvisory, shareText, shareTextUrl,
  translateAdvisory,
} from "../api/client";
import { authConfigured, useUser } from "../auth";
import AlertDialog from "../components/AlertDialog";
import Disclaimer from "../components/Disclaimer";
import { Button, Chip, Dialog, Field, Icon, Segmented, Tabs, nf, useSnackbar } from "../components/m3";
import { MapCanvas } from "../components/MapCanvas";
import OfficialStatus from "../components/OfficialStatus";
import { points } from "../layers/factories";
import type { Advisory as Adv, AdvisoryVersion, AoiStatus, Recommendation, Review, RunResult, Translation } from "../types/api";

type H = Recommendation["horizon"];
const HORIZONS: { value: H; label: string; icon: string; blurb: string }[] = [
  { value: "immediate", label: "Now", icon: "emergency", blurb: "For the incoming storm: who moves first, bridges to close, shelters to open, where to stage teams." },
  { value: "seasonal", label: "Before monsoon", icon: "event_repeat", blurb: "Drains, slopes and roads to inspect; shelters to stock." },
  { value: "structural", label: "Long term", icon: "foundation", blurb: "Where permanent shelters, medical facilities or better roads are justified." },
];
// fixed Hindi terms for departments and figures (mirrors backend DEPARTMENTS_HI / KEY_LABELS_HI)
const DEPT_HI: Record<string, string> = {
  "District Magistrate / DDMA": "ज़िलाधिकारी / DDMA", "SDM / Tehsildar (Revenue)": "SDM / तहसीलदार (राजस्व)", Police: "पुलिस", "SDRF / NDRF": "SDRF / NDRF",
  "PWD (roads and bridges)": "लोक निर्माण विभाग (सड़क व पुल)", "Health (CMO, 108 ambulance)": "स्वास्थ्य (CMO, 108 एम्बुलेंस)",
  "Municipal body (drains, water-logging)": "नगर निकाय (नाले, जलभराव)", "Irrigation / Flood control": "सिंचाई / बाढ़ नियंत्रण",
  "Education (school shelters)": "शिक्षा (स्कूल आश्रय)", "Block Development Officer": "खंड विकास अधिकारी",
  "Fire and Emergency Services": "अग्निशमन एवं आपात सेवाएँ", "Border Roads Organisation": "सीमा सड़क संगठन (BRO)",
};
const KEY_HI: Record<string, string> = { K7: "जिन लोगों को हटाना है", K3: "जिन्हें आश्रय स्थल नहीं मिल रहा", K4: "बंद होने वाले पुल", K1: "बाढ़ के पानी में लोग (अधिकतम)" };
const STATE_LABEL = { draft: "Draft", reviewed: "Reviewed", approved: "Approved" } as const;
const fmtDate = (s?: string) => (s ? new Date(s).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "");
const range = (r?: number[] | null) => (r && r.length === 2 && r[0] !== r[1] ? `${nf(r[0])}–${nf(r[1])}` : "");

function Fly({ to }: { to: { lon: number; lat: number; t: number } | null }) {
  const map = useMap();
  useEffect(() => { if (map && to) { map.panTo({ lat: to.lat, lng: to.lon }); map.setZoom(16); } }, [map, to]);
  return null;
}

function Fit({ pts }: { pts: [number, number][] }) {
  const map = useMap();
  const done = useRef(false);
  useEffect(() => {
    if (!map || done.current || !pts.length) return;
    const b = new google.maps.LatLngBounds();
    pts.forEach(([lon, lat]) => b.extend({ lat, lng: lon }));
    map.fitBounds(b, 40);
    done.current = true;
  }, [map, pts]);
  return null;
}

function ReviewPanel({ adv, viewing, onReview }: { adv: Adv; viewing: number | null; onReview: (s: Review["state"]) => void }) {
  const r = adv.review ?? { state: "draft" as const };
  const steps: Review["state"][] = ["draft", "reviewed", "approved"];
  const at = steps.indexOf(r.state);
  return (
    <section className="card outlined stack-s review-panel" aria-label="Review and approval">
      <div className="row nowrap"><Icon name="approval" /><span className="title-s grow">Review and approval</span><span className="label-m muted">v{adv.version ?? 1}</span></div>
      <ol className="stepper">
        {steps.map((s, i) => <li key={s} className={i <= at ? "done" : ""}><Icon name={i <= at ? "check_circle" : "radio_button_unchecked"} className="sm" fill={i <= at} />{STATE_LABEL[s]}</li>)}
      </ol>
      {r.state !== "draft" && <p className="body-s">{STATE_LABEL[r.state]} by <b>{r.by}</b>{r.designation ? `, ${r.designation}` : ""}{r.verified ? "" : " (unverified name)"} · {fmtDate(r.at)}{r.note ? ` · “${r.note}”` : ""}</p>}
      {viewing == null && r.state !== "approved" && (
        <div className="row">
          {r.state === "draft" && <Button variant="tonal" size="small" icon="rate_review" onClick={() => onReview("reviewed")}>Mark reviewed</Button>}
          <Button size="small" icon="verified" onClick={() => onReview("approved")}>Approve</Button>
        </div>
      )}
      {r.state === "approved" && <p className="body-s muted">Approved versions are locked. Regenerating creates a new draft version; this one stays on record.</p>}
      {adv.approved_version && adv.approved_version !== adv.version && <p className="body-s">Version {adv.approved_version} is the approved brief.</p>}
    </section>
  );
}

export default function Advisory() {
  const { aoiId = "", runId: routeRun } = useParams();
  const nav = useNavigate();
  const snack = useSnackbar();
  const user = useUser();
  const [runId, setRunId] = useState<string | null>(routeRun ?? null);
  const [run, setRun] = useState<RunResult | null>(null);
  const [cur, setCur] = useState<Adv | null>(null);
  const [old, setOld] = useState<Adv | null>(null);  // an older immutable version being viewed
  const [versions, setVersions] = useState<AdvisoryVersion[]>([]);
  const [state, setState] = useState<"loading" | "pending" | "ready" | "none" | "error">("loading");
  const [err, setErr] = useState("");
  const [tab, setTab] = useState<H>("immediate");
  const [fly, setFly] = useState<{ lon: number; lat: number; t: number } | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [status, setStatus] = useState<AoiStatus | null>(null);
  const [lang, setLang] = useState<"en" | "hi">("en");
  const [tr, setTr] = useState<Translation | null>(null);
  const [trBusy, setTrBusy] = useState(false);
  const [rev, setRev] = useState<{ state: Review["state"]; name: string; designation: string; note: string } | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const [alertOpen, setAlertOpen] = useState(false);
  const adv = old ?? cur;

  useEffect(() => {
    getAoiStatus(aoiId).then((s) => { setStatus(s); if (!routeRun) { if (s.latest_run_id) setRunId(s.latest_run_id); else setState("none"); } }).catch(() => undefined);
  }, [aoiId, routeRun]);

  const loadVersions = (id: string) => advisoryVersions(id).then(setVersions).catch(() => setVersions([]));
  useEffect(() => {
    if (!runId) return;
    let stop = false;
    getRun(runId).then(setRun).catch(() => undefined);
    const poll = async (first: boolean) => {
      try {
        const r: any = first ? await requestAdvisory(runId) : await getAdvisory(runId);
        if (stop) return;
        if (r.status === "pending") { setState("pending"); if (r.headline) setCur(r); setTimeout(() => poll(false), 3000); }
        else if (r.status === "error") { setState(r.headline ? "ready" : "error"); setErr(r.error || "Generation failed"); if (r.headline) setCur(r); }
        else { setCur(r); setState("ready"); loadVersions(runId); }
      } catch (e) { if (!stop) { setState("error"); setErr(String((e as Error).message)); } }
    };
    poll(true);
    return () => { stop = true; };
  }, [runId]);

  // Hindi: cached per version on the server; numbers are checked there
  useEffect(() => {
    if (lang !== "hi" || !adv || !runId) { setTr(null); return; }
    const cached = adv.translations?.hi;
    if (cached && cached.version === adv.version) { setTr(cached); return; }
    if (old) { setTr(null); snack("Hindi is available for the current version"); return; }
    setTrBusy(true);
    translateAdvisory(runId, "hi").then(setTr).catch((e) => { snack("Translation unavailable: " + (e as Error).message); setLang("en"); }).finally(() => setTrBusy(false));
  }, [lang, adv?.version, runId, old]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function regenerate() {
    if (!runId) return;
    setOld(null); setState("pending");
    await requestAdvisory(runId, true).catch(() => undefined);
    const tick = async () => {
      const r: any = await getAdvisory(runId).catch(() => ({ status: "pending" }));
      if (r.status === "pending") setTimeout(tick, 3000);
      else if (r.status === "error") { setState(r.headline ? "ready" : "error"); setErr(r.error); }
      else { setCur(r); setState("ready"); loadVersions(runId); snack(`New draft version ${r.version}`); }
    };
    setTimeout(tick, 3000);
  }

  async function submitReview() {
    if (!rev || !runId || !cur) return;
    try {
      const r = await reviewAdvisory(runId, { state: rev.state, name: rev.name, designation: rev.designation, note: rev.note, version: cur.version });
      setCur(r); setRev(null); loadVersions(runId);
      snack(rev.state === "approved" ? "Brief approved and locked" : "Marked as reviewed");
    } catch (e) { snack(String((e as Error).message)); }
  }

  async function copyShare(open: boolean) {
    if (!runId) return;
    try {
      const t = await shareText(runId, lang);
      if (open) window.open(`https://wa.me/?text=${encodeURIComponent(t)}`, "_blank", "noopener");
      else { await navigator.clipboard.writeText(t); snack("Copied: paste into WhatsApp, SMS or email"); }
    } catch (e) { snack("Could not prepare the text: " + (e as Error).message); }
    setShareOpen(false);
  }

  const recs = adv?.recommendations ?? [];
  const T = (r: Recommendation) => (tr?.recommendations[r.id] ?? null);
  const markers = useMemo(() => recs.filter((r) => r.lonlat).map((r) => ({ lon: r.lonlat![0], lat: r.lonlat![1], id: r.id, p: r.priority })), [recs]);
  const layers = useMemo(() => points("recos", markers, (m) => (m.id === sel ? [11, 87, 208, 255] : m.p === "P1" ? [217, 48, 37, 255] : m.p === "P2" ? [242, 153, 0, 255] : [26, 115, 232, 255]),
    (m) => (m.id === sel ? 11 : 8), (m) => m.id), [markers, sel]);
  const centre: [number, number] | null = status?.bbox ? [(status.bbox[0] + status.bbox[2]) / 2, (status.bbox[1] + status.bbox[3]) / 2] : null;
  const bd = adv?.breakdown ?? run?.demand_breakdown ?? {};
  const k7 = adv?.key_numbers.find((k) => k.evidence_id === "K7");
  const deadline = adv?.recommendations.find((r) => r.horizon === "immediate" && r.act_by_hour === adv?.evac_window_h)?.act_by;

  if (state === "none") return (
    <div className="doc-page"><div className="doc" style={{ alignItems: "center", textAlign: "center", paddingTop: 96 }}>
      <Icon name="assignment" className="xl muted" /><h1 className="headline-s">No scenario yet</h1>
      <p className="body-m muted">Run a scenario on the map first; the brief is drafted from its results.</p>
      <Button icon="map" onClick={() => nav(`/area/${aoiId}`)}>Open the map</Button>
    </div></div>
  );

  return (
    <div className="doc-page">
      <div className="doc" style={{ maxWidth: 1240 }}>
        <div className="doc-head">
          <div className="grow stack-s">
            <div className="row" style={{ gap: 8 }}>
              <span className="label-l muted">Brief · {status?.name ?? ""}</span>
              {adv && <span className={`state-chip ${adv.review?.state ?? "draft"}`}>{STATE_LABEL[adv.review?.state ?? "draft"]} · v{adv.version ?? 1}</span>}
              {adv && <Chip small icon={adv.generated_by === "gemini" ? "auto_awesome" : "rule"} label={adv.generated_by === "gemini" ? "Drafted with Gemini, checked against the model" : "Rules-based brief"} title={adv.model || "Deterministic fallback"} />}
            </div>
            <h1 className="bottom-line" lang={lang}>{tr?.headline ?? adv?.headline ?? (state === "error" ? "The brief could not be generated" : "Drafting the brief…")}</h1>
            {(tr?.summary ?? adv?.summary) && <p className="body-l summary" lang={lang}>{tr?.summary ?? adv?.summary}</p>}
            {run && <span className="body-s muted">Scenario: {run.rain_label}{run.start_local ? ` · starts ${fmtDate(run.start_local)}` : " · hypothetical rain, times are hours after the rain starts"} · {fmtDate(run.created_at)}</span>}
          </div>
          <div className="stack-s no-print" style={{ alignItems: "flex-end" }}>
            <Segmented label="Language" value={lang} onChange={setLang} options={[{ value: "en", label: "English" }, { value: "hi", label: "हिन्दी" }]} />
            <div className="row" style={{ gap: 4 }} data-tour="adv-actions">
              <Button variant="tonal" icon="share" onClick={() => setShareOpen(true)} disabled={!cur}>Share</Button>
              <Button variant="tonal" icon="campaign" onClick={() => setAlertOpen(true)} disabled={!runId}>Public alert</Button>
              <Button variant="text" icon="print" onClick={() => window.print()} disabled={!adv}>Print</Button>
            </div>
          </div>
        </div>
        {trBusy && <div className="notice info"><span className="spinner small" /> Translating with Gemini; numbers are checked against the English brief…</div>}
        {tr && tr.kept_english.length > 0 && <div className="notice warn"><Icon name="translate" />{tr.kept_english.length} item(s) stay in English because a number changed in translation.</div>}
        {old && <div className="notice warn"><Icon name="history" />You are viewing version {old.version} ({STATE_LABEL[old.review?.state ?? "draft"]}). <button className="btn btn-text small sl" onClick={() => setOld(null)}>Back to the current version</button></div>}
        <Disclaimer card className="screen-hide" />

        {(state === "pending" || state === "loading") && !adv ? (
          <div className="stack">
            <div className="notice info"><Icon name="auto_awesome" className="gemini-text" /><span>Gemini is drafting the brief from this scenario's facts. Every recommendation is checked against the numbers and places before it is shown. About a minute.</span></div>
            <div className="metrics" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>{[0, 1, 2, 3].map((i) => <div key={i} className="shimmer" style={{ height: 84 }} />)}</div>
            {[0, 1, 2].map((i) => <div key={i} className="shimmer" style={{ height: 120 }} />)}
          </div>
        ) : state === "error" && !adv ? (
          <div className="notice error"><Icon name="error" /><span>{err}. Try Regenerate; if Gemini is unavailable a rules-based brief is produced.</span></div>
        ) : adv && (
          <>
            {state === "pending" && <div className="notice info"><span className="spinner small" /> Drafting a new version; the current one stays below until it is ready.</div>}
            {k7 && k7.value > 0 && (
              <div className="deadline">
                <Icon name="schedule" fill />
                <div className="grow">
                  <div className="title-m">{deadline ? `Move people ${deadline}` : "Move people as early as possible"}</div>
                  <div className="body-s">About {nf(k7.rounded ?? k7.value)} people{range(k7.range) ? ` (${range(k7.range)})` : ""}:
                    {bd.flood ? ` ${nf(bd.flood)} in flood water` : ""}.
                    The range shows what happens if flood depths are 30% lower or higher and the population 20% lower or higher.</div>
                </div>
              </div>
            )}

            <div className="brief-top">
              <div className="metrics" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
                {adv.key_numbers.slice(0, 4).map((k) => (
                  <div key={k.evidence_id} className={`metric ${k.evidence_id === "K3" && k.value > 0 ? "alert" : ""}`} title={`Exact model value ${k.value} (${k.evidence_id})`}>
                    <span className="l" lang={tr ? "hi" : "en"}>{tr ? KEY_HI[k.evidence_id] ?? k.label : k.label}</span>
                    <span className="v">{k.unit === "people" ? `≈ ${nf(k.rounded ?? k.value)}` : typeof k.value === "number" && !Number.isInteger(k.value) ? k.value : nf(k.value)}</span>
                    <span className="body-s muted">{range(k.range) ? `range ${range(k.range)}` : k.unit === "people" ? "people" : k.unit}</span>
                  </div>
                ))}
              </div>
              <OfficialStatus aoiId={aoiId} official={status?.official} centre={centre} onChange={(o) => setStatus((s) => (s ? { ...s, official: o } : s))} />
            </div>

            <div className="adv-grid" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 380px", gap: 24, alignItems: "start" }}>
              <div className="stack">
                <div className="no-print"><Tabs value={tab} onChange={setTab} withIcons tabs={HORIZONS.map((h) => ({ value: h.value, label: h.label, icon: h.icon, badge: recs.filter((r) => r.horizon === h.value).length }))} /></div>
                {HORIZONS.map((h) => (
                  <section key={h.value} className={`stack ${tab === h.value ? "" : "screen-hide"}`}>
                    <div className="stack-s"><h2 className="title-l">{h.label}</h2><p className="body-m muted">{h.blurb}</p></div>
                    {recs.filter((r) => r.horizon === h.value).map((r, i) => {
                      const t = T(r);
                      return (
                        <article key={r.id} className="reco" style={{ animationDelay: `${i * 50}ms`, borderColor: sel === r.id ? "var(--primary)" : undefined }}
                          onMouseEnter={() => setSel(r.id)} lang={t ? lang : "en"}>
                          <div className="row nowrap" style={{ alignItems: "flex-start" }}>
                            <span className={`prio ${r.priority}`} title={r.priority === "P1" ? "Life safety in the scenario window" : r.priority === "P2" ? "Important" : "Planning"}>{r.priority}</span>
                            <div className="action grow">{t?.action ?? r.action}</div>
                          </div>
                          <dl className="who-when">
                            <div><dt><Icon name="location_on" className="sm" />Where</dt><dd>{r.lonlat
                              ? <button className="linklike" onClick={() => { setSel(r.id); setFly({ lon: r.lonlat![0], lat: r.lonlat![1], t: Date.now() }); }}>{t?.location_label ?? r.location_label}</button>
                              : (t?.location_label ?? r.location_label)}</dd></div>
                            <div><dt><Icon name="badge" className="sm" />Who</dt><dd>{tr ? DEPT_HI[r.owner ?? ""] ?? r.owner : r.owner || "District Magistrate / DDMA"}</dd></div>
                            <div><dt><Icon name="schedule" className="sm" />By when</dt><dd>{t?.act_by ?? r.act_by ?? ""}</dd></div>
                          </dl>
                          <div className="why screen-hide">{t?.why ?? r.why}</div>
                          <details className="why-d no-print"><summary>Why ({r.confidence} confidence)</summary>
                            <div className="why">{t?.why ?? r.why}</div>
                            <div className="row" style={{ gap: 4 }}>{r.evidence_ids.map((e) => <Chip key={e} small label={e} title="Item in this scenario's facts; numbers were checked against it" />)}</div>
                          </details>
                        </article>
                      );
                    })}
                    {!recs.some((r) => r.horizon === h.value) && <p className="body-m muted">No recommendations for this horizon.</p>}
                  </section>
                ))}

                {adv.supplies && adv.supplies.length > 0 && (
                  <section className="card tonal stack-s" aria-label="Supplies">
                    <div className="section-title"><Icon name="inventory_2" /> Relief supplies for {adv.supply_days ?? 3} days</div>
                    <table className="tbl">
                      <thead><tr><th>Item</th><th className="r">For ≈ {nf(k7?.rounded ?? k7?.value ?? 0)} people</th><th className="r">Plan up to</th><th>Basis</th></tr></thead>
                      <tbody>{adv.supplies.map((s, i) => (
                        <tr key={s.item}><td lang={tr ? lang : "en"}>{tr?.supplies[i] ?? s.item}</td><td className="r">{nf(s.quantity)} {s.unit}</td><td className="r">{nf(s.quantity_high)}</td><td className="body-s muted">{s.basis}</td></tr>
                      ))}</tbody>
                    </table>
                    <span className="body-s muted">Sphere Handbook (2018) minimum standards. “Plan up to” uses the high end of the range.</span>
                  </section>
                )}
              </div>

              <div className="stack no-print" style={{ position: "sticky", top: 16 }}>
                <ReviewPanel adv={adv} viewing={old ? old.version ?? null : null}
                  onReview={(s) => setRev({ state: s, name: user?.name ?? "", designation: "", note: "" })} />
                <div className="mini-map card elevated" style={{ padding: 0, height: 340 }}>
                  <MapCanvas center={{ lat: centre?.[1] ?? 22, lng: centre?.[0] ?? 79 }} zoom={13} layers={layers} mapTypeId="hybrid" streetView={false}>
                    <Fit pts={markers.map((m) => [m.lon, m.lat])} />
                    <Fly to={fly} />
                  </MapCanvas>
                </div>
                <div className="row body-s muted"><span className="prio P1">P1</span> life safety <span className="prio P2">P2</span> important <span className="prio P3">P3</span> planning</div>
                {versions.length > 1 && (
                  <section className="stack-s">
                    <span className="label-l">Versions</span>
                    {versions.map((v) => (
                      <button key={v.version} className={`version-row sl ${adv.version === v.version ? "on" : ""}`}
                        onClick={async () => { if (v.version === cur?.version) setOld(null); else if (runId) setOld(await advisoryVersion(runId, v.version)); }}>
                        <span className="title-s">v{v.version}</span><span className={`state-chip ${v.review?.state ?? "draft"}`}>{STATE_LABEL[v.review?.state ?? "draft"]}</span>
                        <span className="body-s muted grow" style={{ textAlign: "right" }}>{fmtDate(v.created_at)}</span>
                      </button>
                    ))}
                  </section>
                )}
                <div className="row">
                  <Button variant="text" size="small" icon="refresh" onClick={regenerate} disabled={state === "pending"}>New version</Button>
                  <a className="body-s" href={runId ? shareTextUrl(runId, lang) : "#"} target="_blank" rel="noreferrer">Text-only version</a>
                  <span className="spacer" />
                  <Link to={`/area/${aoiId}`} className="body-s row"><Icon name="map" className="sm" /> Map</Link>
                </div>
              </div>
            </div>

            <section className="card tonal stack">
              <div className="section-title"><Icon name="report" /> Limitations</div>
              <ul className="body-m" style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }} lang={tr ? lang : "en"}>{(tr?.limitations ?? adv.limitations).map((l, i) => <li key={i}>{l}</li>)}</ul>
              {adv.dropped.length > 0 && (
                <details className="body-s muted"><summary style={{ cursor: "pointer" }}>The checker removed {adv.dropped.length} unsupported suggestion(s)</summary>
                  <ul>{adv.dropped.map((d, i) => <li key={i}>{d.action}: {d.reason}</li>)}</ul></details>
              )}
              {tr && <p className="body-s" lang="hi">{tr.disclaimer}</p>}
            </section>
          </>
        )}
      </div>

      <Dialog open={!!rev} title={rev?.state === "approved" ? "Approve this brief" : "Mark as reviewed"} icon={rev?.state === "approved" ? "verified" : "rate_review"} onClose={() => setRev(null)}
        actions={<><Button variant="text" onClick={() => setRev(null)}>Cancel</Button><Button onClick={submitReview} disabled={!rev?.name.trim()}>{rev?.state === "approved" ? "Approve" : "Mark reviewed"}</Button></>}>
        {rev && (
          <div className="stack">
            <p className="body-s muted">{rev.state === "approved" ? "Approving locks version " + (cur?.version ?? 1) + ". It is recorded with your name and time in the audit trail." : "Recorded with your name and time in the audit trail."}
              {!authConfigured && " Sign-in is not set up on this deployment, so your typed name is recorded as unverified."}</p>
            <Field label="Your name"><input value={rev.name} disabled={!!user} placeholder=" " onChange={(e) => setRev({ ...rev, name: e.target.value })} /></Field>
            <Field label="Designation" support="e.g. District Magistrate, Rudraprayag"><input value={rev.designation} placeholder=" " onChange={(e) => setRev({ ...rev, designation: e.target.value })} /></Field>
            <Field label="Note (optional)"><input value={rev.note} placeholder=" " onChange={(e) => setRev({ ...rev, note: e.target.value })} /></Field>
          </div>
        )}
      </Dialog>

      <AlertDialog runId={runId} open={alertOpen} onClose={() => setAlertOpen(false)} />

      <Dialog open={shareOpen} title="Share the brief" icon="share" onClose={() => setShareOpen(false)} actions={<Button variant="text" onClick={() => setShareOpen(false)}>Close</Button>}>
        <div className="stack">
          <p className="body-s muted">Plain text with the bottom line, key figures, actions with owner and deadline, supplies, review state and the disclaimer ({lang === "hi" ? "Hindi" : "English"}).</p>
          <Button icon="content_copy" onClick={() => copyShare(false)}>Copy text</Button>
          <Button variant="tonal" icon="chat" onClick={() => copyShare(true)}>Open in WhatsApp</Button>
          <Button variant="outlined" icon="print" onClick={() => { setShareOpen(false); window.print(); }}>Print or save as PDF</Button>
          {cur?.review?.state !== "approved" && <div className="notice warn"><Icon name="info" />This version is not approved yet; the text says DRAFT.</div>}
        </div>
      </Dialog>
    </div>
  );
}
