import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMap } from "@vis.gl/react-google-maps";
import { getAdvisory, getAoiStatus, getRun, requestAdvisory } from "../api/client";
import Disclaimer from "../components/Disclaimer";
import { Button, Chip, Icon, Tabs, nf, useSnackbar } from "../components/m3";
import { MapCanvas } from "../components/MapCanvas";
import { points } from "../layers/factories";
import type { Advisory as Adv, Recommendation, RunResult } from "../types/api";

type H = Recommendation["horizon"];
const HORIZONS: { value: H; label: string; icon: string; blurb: string }[] = [
  { value: "immediate", label: "Immediate", icon: "emergency", blurb: "For the incoming storm: who moves first, routes, shelters, bridges, staging." },
  { value: "seasonal", label: "Seasonal", icon: "event_repeat", blurb: "Before the monsoon: drains, slopes and roads to inspect, shelters to stock." },
  { value: "structural", label: "Structural", icon: "foundation", blurb: "Long term: where permanent shelters, medical facilities or better roads are justified." },
];
const CONF = { low: "", medium: "info", high: "ok" } as const;

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

export default function Advisory() {
  const { aoiId = "", runId: routeRun } = useParams();
  const nav = useNavigate();
  const snack = useSnackbar();
  const [runId, setRunId] = useState<string | null>(routeRun ?? null);
  const [run, setRun] = useState<RunResult | null>(null);
  const [adv, setAdv] = useState<Adv | null>(null);
  const [state, setState] = useState<"loading" | "pending" | "ready" | "none" | "error">("loading");
  const [err, setErr] = useState("");
  const [tab, setTab] = useState<H>("immediate");
  const [fly, setFly] = useState<{ lon: number; lat: number; t: number } | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [name, setName] = useState("");

  useEffect(() => {
    getAoiStatus(aoiId).then((s) => { setName(s.name ?? ""); if (!routeRun) { if (s.latest_run_id) setRunId(s.latest_run_id); else setState("none"); } }).catch(() => undefined);
  }, [aoiId, routeRun]);

  useEffect(() => {
    if (!runId) return;
    let stop = false;
    getRun(runId).then(setRun).catch(() => undefined);
    const poll = async (first: boolean) => {
      try {
        const r: any = first ? await requestAdvisory(runId) : await getAdvisory(runId);
        if (stop) return;
        if (r.status === "pending") { setState("pending"); setTimeout(() => poll(false), 3000); }
        else if (r.status === "error") { setState("error"); setErr(r.error || "Generation failed"); }
        else { setAdv(r); setState("ready"); }
      } catch (e) { if (!stop) { setState("error"); setErr(String((e as Error).message)); } }
    };
    poll(true);
    return () => { stop = true; };
  }, [runId]);

  async function regenerate() {
    if (!runId) return;
    setAdv(null); setState("pending");
    await requestAdvisory(runId, true).catch(() => undefined);
    const tick = async () => {
      const r: any = await getAdvisory(runId).catch(() => ({ status: "pending" }));
      if (r.status === "pending") setTimeout(tick, 3000); else if (r.status === "error") { setState("error"); setErr(r.error); } else { setAdv(r); setState("ready"); snack("Brief regenerated"); }
    };
    setTimeout(tick, 3000);
  }

  const recs = adv?.recommendations ?? [];
  const markers = useMemo(() => recs.filter((r) => r.lonlat).map((r) => ({ lon: r.lonlat![0], lat: r.lonlat![1], id: r.id, p: r.priority })), [recs]);
  const layers = useMemo(() => points("recos", markers, (m) => (m.id === sel ? [11, 87, 208, 255] : m.p === "P1" ? [217, 48, 37, 255] : m.p === "P2" ? [242, 153, 0, 255] : [26, 115, 232, 255]),
    (m) => (m.id === sel ? 11 : 8), (m) => m.id), [markers, sel]);

  if (state === "none") return (
    <div className="doc-page"><div className="doc" style={{ alignItems: "center", textAlign: "center", paddingTop: 96 }}>
      <Icon name="assignment" className="xl muted" /><h1 className="headline-s">No scenario yet</h1>
      <p className="body-m muted">Run a scenario on the map first; the advisory brief is drafted from its results.</p>
      <Button icon="map" onClick={() => nav(`/area/${aoiId}`)}>Open the map</Button>
    </div></div>
  );

  return (
    <div className="doc-page">
      <div className="doc" style={{ maxWidth: 1240 }}>
        <div className="doc-head">
          <div className="grow stack-s">
            <span className="label-l muted">Advisory brief · {name}</span>
            <h1>{adv?.headline ?? (state === "error" ? "The brief could not be generated" : "Drafting the brief…")}</h1>
            {run && <span className="body-m muted">{run.rain_label} · run {run.run_id} · {new Date(run.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</span>}
          </div>
          <div className="row no-print">
            {adv && <Chip icon={adv.generated_by === "gemini" ? "auto_awesome" : "rule"} label={adv.generated_by === "gemini" ? "Drafted with Gemini" : "Rules-based brief"}
              title={adv.model || "Deterministic fallback"} />}
            <Button variant="text" icon="refresh" onClick={regenerate} disabled={state === "pending"}>Regenerate</Button>
            <Button variant="tonal" icon="print" onClick={() => window.print()} disabled={!adv}>Print or save PDF</Button>
          </div>
        </div>

        <Disclaimer card />

        {state === "pending" || state === "loading" ? (
          <div className="stack">
            <div className="notice info"><Icon name="auto_awesome" className="gemini-text" /><span>Gemini is drafting the brief from this scenario's facts. Every recommendation is checked against the numbers and ids before it is shown. This takes about a minute.</span></div>
            <div className="metrics" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>{[0, 1, 2, 3].map((i) => <div key={i} className="shimmer" style={{ height: 84 }} />)}</div>
            {[0, 1, 2].map((i) => <div key={i} className="shimmer" style={{ height: 140 }} />)}
          </div>
        ) : state === "error" ? (
          <div className="notice error"><Icon name="error" /><span>{err}. Try Regenerate; if Gemini is unavailable a rules-based brief is produced.</span></div>
        ) : adv && (
          <>
            <div className="metrics" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>
              {adv.key_numbers.map((k) => (
                <div key={k.evidence_id} className={`metric ${k.evidence_id === "K3" && k.value > 0 ? "alert" : ""}`}>
                  <span className="l">{k.label}</span>
                  <span className="v">{typeof k.value === "number" && !Number.isInteger(k.value) ? k.value : nf(k.value)}</span>
                  <span className="body-s muted">{k.unit} · {k.evidence_id}</span>
                </div>
              ))}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 420px", gap: 24, alignItems: "start" }} className="adv-grid">
              <div className="stack">
                <div className="no-print"><Tabs value={tab} onChange={setTab} withIcons tabs={HORIZONS.map((h) => ({ value: h.value, label: h.label, icon: h.icon, badge: recs.filter((r) => r.horizon === h.value).length }))} /></div>
                {HORIZONS.map((h) => (
                  <section key={h.value} className={`stack ${tab === h.value ? "" : "screen-hide"}`}>
                    <div className="stack-s"><h2 className="title-l">{h.label}</h2><p className="body-m muted">{h.blurb}</p></div>
                    {recs.filter((r) => r.horizon === h.value).map((r, i) => (
                      <article key={r.id} className="reco" style={{ animationDelay: `${i * 60}ms`, borderColor: sel === r.id ? "var(--primary)" : undefined }}
                        onMouseEnter={() => setSel(r.id)}>
                        <div className="row nowrap">
                          <span className={`prio ${r.priority}`}>{r.priority}</span>
                          <span className="label-m muted">{r.id}</span>
                          <span className="spacer" />
                          <span className={`tag ${CONF[r.confidence]}`}>{r.confidence} confidence</span>
                        </div>
                        <div className="action">{r.action}</div>
                        <div className="why">{r.why}</div>
                        <div className="row">
                          {r.lonlat ? <Button variant="text" size="small" icon="location_on" onClick={() => { setSel(r.id); setFly({ lon: r.lonlat![0], lat: r.lonlat![1], t: Date.now() }); }}>{r.location_label}</Button>
                            : <span className="body-s muted row"><Icon name="location_on" className="sm" />{r.location_label}</span>}
                          <span className="spacer" />
                          {r.evidence_ids.map((e) => <Chip key={e} small label={e} title="Evidence id in the scenario facts" />)}
                        </div>
                      </article>
                    ))}
                    {!recs.some((r) => r.horizon === h.value) && <p className="body-m muted">No recommendations for this horizon.</p>}
                  </section>
                ))}
              </div>
              <div className="stack no-print" style={{ position: "sticky", top: 16 }}>
                <div className="mini-map card elevated" style={{ padding: 0, height: 420 }}>
                  <MapCanvas center={{ lat: 30.28, lng: 78.98 }} zoom={13} layers={layers} mapTypeId="hybrid">
                    <Fit pts={markers.map((m) => [m.lon, m.lat])} />
                    <Fly to={fly} />
                  </MapCanvas>
                </div>
                <div className="row body-s muted"><span className="prio P1">P1</span> life safety in the scenario window <span className="prio P2">P2</span> <span className="prio P3">P3</span></div>
                <Link to={`/area/${aoiId}`} className="body-m row"><Icon name="map" className="sm" /> Back to the scenario map</Link>
              </div>
            </div>

            <section className="card tonal stack">
              <div className="section-title"><Icon name="report" /> Limitations</div>
              <ul className="body-m" style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }}>{adv.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
              {adv.dropped.length > 0 && (
                <details className="body-s muted"><summary style={{ cursor: "pointer" }}>Validator removed {adv.dropped.length} unsupported suggestion(s)</summary>
                  <ul>{adv.dropped.map((d, i) => <li key={i}>{d.action}: {d.reason}</li>)}</ul></details>
              )}
              <p className="body-s muted">Evidence ids (K, C, S, A, B, R, RT, L, G, M, H, X, V) refer to items in this scenario's facts. Numbers in each “why” were checked against them automatically.</p>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
