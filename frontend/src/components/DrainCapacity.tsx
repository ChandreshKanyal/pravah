// Storm-drain capacity under built-up land: the most uncertain number in the waterlogging model. Default 25 mm/h
// (Mumbai's historical standard); Gemini with Google Search can look up the city's figure with sources, and a person
// confirms it before any run uses it. A slider sets it for one scenario only.
import { useState } from "react";
import { lookupDrain, setDrain } from "../api/client";
import type { AreaDrain, DrainLookup, ScenarioParams } from "../types/api";
import { Button, Icon, Slider, useSnackbar } from "./m3";

const host = (u: { uri: string; title?: string }) => u.title || (() => { try { return new URL(u.uri).hostname.replace(/^www\./, ""); } catch { return u.uri; } })();

export default function DrainCapacity({ aoiId, p, set, drain, onSaved }: {
  aoiId: string; p: ScenarioParams; set: (patch: Partial<ScenarioParams>) => void; drain: AreaDrain | null | undefined;
  onSaved: (d: AreaDrain | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [found, setFound] = useState<DrainLookup | null>(null);
  const snack = useSnackbar();
  const area = drain?.mm_h ?? 25;
  const value = p.drain_capacity_mm_h ?? area;
  const look = async () => {
    setBusy(true); setFound(null);
    try { setFound(await lookupDrain(aoiId)); } catch (e) { snack(String((e as Error).message)); } finally { setBusy(false); }
  };
  const use = async (f: DrainLookup) => {
    const r = await setDrain(aoiId, { mm_h: f.mm_h, city: f.city, basis: f.basis, sources: f.sources }).catch((e) => { snack(String(e.message)); return null; });
    if (!r) return;
    onSaved(r.drain); set({ drain_capacity_mm_h: null }); setFound(null);
    snack(`Storm drains set to ${f.mm_h} mm/h for this area. Press Run scenario.`);
  };
  const reset = async () => {
    const r = await setDrain(aoiId, { mm_h: null }).catch(() => null);
    if (r) { onSaved(null); set({ drain_capacity_mm_h: null }); }
  };
  return (
    <div className="stack-s">
      <Slider label="Storm drains carry" unit="mm/h" value={value} min={5} max={100} step={1}
        onChange={(v) => set({ drain_capacity_mm_h: v === area ? null : v })}
        hint={p.drain_capacity_mm_h != null ? `This scenario only (area: ${area} mm/h)`
          : drain ? `Confirmed for ${drain.city || "this area"}: ${drain.basis}` : "Default: Mumbai's historical design standard. Rain beyond it waterlogs built-up hollows."} />
      <div className="row" style={{ gap: 4 }}>
        <Button variant="tonal" size="small" icon={busy ? undefined : "travel_explore"} disabled={busy} onClick={look}>
          {busy ? <><span className="spinner small" /> Searching…</> : "Look up this city"}</Button>
        {drain && <Button variant="text" size="small" onClick={reset}>Back to 25 mm/h</Button>}
      </div>
      {found && (
        <div className="drain-found">
          <div className="row nowrap"><Icon name="auto_awesome" className="sm gemini-text" />
            <span className="title-s grow">{found.found ? `${found.city}: ${found.mm_h} mm/h` : found.city || "No figure found"}</span></div>
          {found.basis && <p className="body-s" style={{ margin: 0 }}>{found.basis}</p>}
          {found.planned_mm_h != null && <p className="body-s muted" style={{ margin: 0 }}>Planned upgrade: {found.planned_mm_h} mm/h (not used until built).</p>}
          {found.candidates && <p className="body-s" style={{ margin: 0 }}>Two searches gave {found.candidates.map((c) => `${c.mm_h} mm/h`).join(" and ")}.</p>}
          {found.note && <p className="body-s muted" style={{ margin: 0 }}>{found.note}</p>}
          {found.sources.length > 0 && <div className="src">{found.sources.map((s) => <a key={s.uri} href={s.uri} target="_blank" rel="noreferrer">{host(s)}</a>)}</div>}
          <div className="row" style={{ justifyContent: "flex-end", gap: 4 }}>
            <Button variant="text" size="small" onClick={() => setFound(null)}>Dismiss</Button>
            {found.found && <Button size="small" icon="check" onClick={() => use(found)}>Use {found.mm_h} mm/h</Button>}
          </div>
          <p className="body-s muted" style={{ margin: 0 }}>Found by Gemini with Google Search. Check the sources before using it.</p>
        </div>
      )}
    </div>
  );
}
