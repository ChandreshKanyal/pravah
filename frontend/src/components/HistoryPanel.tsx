import SearchChip from "./SearchChip";
import { useEffect, useState } from "react";
import { historyAoi } from "../api/client";
import type { HistoryAoi } from "../types/api";
import { Button, Icon, nf } from "./m3";

/** S11 AOI incidents: datasets (GFD) and grounded web leads, kept apart from modelled risk. */
export default function HistoryPanel({ aoiId, onFly, onData }: { aoiId: string; onFly: (lon: number, lat: number) => void; onData: (h: HistoryAoi) => void }) {
  const [h, setH] = useState<HistoryAoi | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { historyAoi(aoiId).then((x) => { setH(x); onData(x); }).catch((e) => setErr(String(e.message))); }, [aoiId, onData]);
  async function web() {
    setBusy(true);
    try {
      let x = await historyAoi(aoiId, true);
      for (let i = 0; i < 40 && (x as any).web_status === "pending"; i++) {  // background job, ~1 min
        await new Promise((r) => setTimeout(r, 4000));
        x = await historyAoi(aoiId);
      }
      setH(x); onData(x);
    } catch (e) { setErr(String((e as Error).message)); } finally { setBusy(false); }
  }
  if (err) return <div className="notice error"><Icon name="error" />{err}</div>;
  if (!h) return <div className="stack-s"><div className="shimmer" style={{ height: 72 }} /><div className="shimmer" style={{ height: 120 }} /></div>;
  return (
    <div className="stack">
      <div className="notice info"><Icon name="history" /><span>Historical incidents, not predictions. They show where disasters were recorded before.</span></div>

      <section className="group">
        <div className="section-title"><Icon name="flood" /> Observed floods <span className="body-s muted">· {h.labels?.gfd ?? "Global Flood Database"}</span></div>
        {h.gfd_events.length ? h.gfd_events.slice(0, 8).map((e, i) => (
          <div key={i} className="li dense" style={{ padding: "4px 0" }}>
            <span className="txt"><span className="t" style={{ fontSize: 14 }}>{e.start} → {e.end}</span>
              <span className="s" style={{ display: "block" }}>{e.cause || "flood"} · {e.flooded_km2_in_area} km² in area{e.dead ? ` · ${nf(e.dead)} deaths (event)` : ""}</span></span>
          </div>
        )) : <p className="body-s muted">No MODIS-detected flood inside this box (2000–2018). Narrow valleys are often below MODIS's 250 m resolution.</p>}
        {h.agreement_pct != null && <div className="notice ok"><Icon name="verified" /><span>{h.agreement_pct}% of historically flooded cells fall in our high flood-susceptibility zones. {h.note}</span></div>}
      </section>

      <section className="group">
        <div className="section-title"><Icon name="travel_explore" /> From web sources <span className="body-s muted">· unverified leads</span></div>
        {!h.web && <>
          <p className="body-s muted">Gemini with Google Search grounding lists documented floods and cloudbursts here since 2000, each with a source link.</p>
          <Button variant="tonal" icon="travel_explore" onClick={web} disabled={busy}>{busy ? "Searching the web (about a minute)…" : "Find web incidents"}</Button>
        </>}
        {h.web?.map((w, i) => (
          <div key={i} className="card outlined stack-s" style={{ padding: 12 }}>
            <div className="row nowrap"><span className="tag warn">{w.type}</span><span className="label-m muted grow">{w.date}</span>
              {w.marker && <button className="icon-btn small sl" aria-label="Show on map" onClick={() => onFly(w.marker!.lng, w.marker!.lat)}><Icon name="my_location" /></button>}</div>
            <span className="title-s">{w.place}</span>
            <span className="body-s">{w.summary}</span>
            <div className="row">{w.source_urls.map((u) => <a key={u} className="body-s" href={u} target="_blank" rel="noreferrer">{new URL(u).hostname.replace("www.", "")} <Icon name="open_in_new" className="sm" /></a>)}</div>
          </div>
        ))}
        {h.search_entry_point && <SearchChip html={h.search_entry_point} />}
      </section>
    </div>
  );
}
