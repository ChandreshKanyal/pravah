import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createAoi } from "../api/client";
import DrawControl, { bboxKm, bboxOf, type DrawMode } from "../components/DrawControl";
import { MapCanvas } from "../components/MapCanvas";

const LIMIT_KM = { river: 15, urban: 4 } as const;
const DEMOS = [
  { name: "Rudraprayag (Alaknanda-Mandakini confluence)", bbox: [78.93, 30.24, 79.03, 30.33] as [number, number, number, number], mode: "river" as const },
];

export default function Explore() {
  const nav = useNavigate();
  const [mode, setMode] = useState<DrawMode>(null);
  const [draft, setDraft] = useState<{ bbox: [number, number, number, number]; name: string; mode: "river" | "urban" } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const size = draft ? bboxKm(draft.bbox) : null;
  const tooBig = draft && size ? size[0] > LIMIT_KM[draft.mode] || size[1] > LIMIT_KM[draft.mode] : false;

  async function submit() {
    if (!draft || tooBig) return;
    setBusy(true);
    setError(null);
    try {
      const r = await createAoi(draft.bbox, draft.name || "Unnamed area", draft.mode);
      nav(`/area/${r.aoi.aoi_id}`);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="explore">
      <MapCanvas center={{ lat: 22.5, lng: 79 }} zoom={5}>
        <DrawControl mode={mode} onFinish={(p) => { setMode(null); setDraft({ bbox: bboxOf(p), name: "", mode: "river" }); }} />
      </MapCanvas>
      <aside className="explore-panel card">
        <h2>Choose an area</h2>
        <p className="muted">Draw a rectangle over a hill town or a flood-prone ward. River mode allows up to 15 × 15 km; urban mode up to 4 × 4 km.</p>
        <button className="primary" onClick={() => setMode(mode === "rectangle" ? null : "rectangle")}>
          {mode === "rectangle" ? "Cancel drawing" : "Draw area"}
        </button>
        <h3>Demo areas</h3>
        {DEMOS.map((d) => (
          <button key={d.name} className="link" onClick={() => setDraft({ ...d })}>{d.name}</button>
        ))}
        {draft && size && (
          <div className="draft">
            <h3>New area</h3>
            <p>{size[0].toFixed(1)} km × {size[1].toFixed(1)} km</p>
            <label>Name <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="e.g. Rudraprayag town" /></label>
            <label>Mode
              <select value={draft.mode} onChange={(e) => setDraft({ ...draft, mode: e.target.value as "river" | "urban" })}>
                <option value="river">River (HAND flood + landslide)</option>
                <option value="urban">Urban (water-logging screening)</option>
              </select>
            </label>
            {tooBig && <p className="error">Too large for {draft.mode} mode (max {LIMIT_KM[draft.mode]} × {LIMIT_KM[draft.mode]} km). Draw a smaller area.</p>}
            {error && <p className="error">{error}</p>}
            <div className="row">
              <button className="primary" disabled={busy || !!tooBig} onClick={submit}>{busy ? "Starting…" : "Prepare area"}</button>
              <button onClick={() => setDraft(null)}>Cancel</button>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
