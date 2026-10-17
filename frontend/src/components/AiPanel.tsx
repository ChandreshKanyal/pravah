// "AI what-if": the per-area emulator of the 2D flow model answers in milliseconds, so the rain can be dragged and the
// flood redrawn live; and the rain triggers (mm in 1, 3, 6 h per settlement) derived from it for early action.
import { useEffect, useRef, useState } from "react";
import { emulatorPng, getEmulator, getTriggers, predictEmulator, trainEmulator, type WhatIf } from "../api/client";
import type { EmulatorStats, EmulatorStatus, ScenarioParams, Triggers } from "../types/api";
import { Button, HelpTip, Icon, Linear, Segmented, Slider, nf, useSnackbar } from "./m3";

const IMD_TAG: Record<string, string> = { "below heavy": "ok", heavy: "mod", "very heavy": "high", "extremely heavy": "crit" };

export default function AiPanel({ aoiId, urban, onPreview, onRunThis, onFly }: {
  aoiId: string; urban: boolean; onPreview: (png: string | null) => void;
  onRunThis: (patch: Partial<ScenarioParams>) => void; onFly: (lon: number, lat: number) => void;
}) {
  const snack = useSnackbar();
  const [st, setSt] = useState<EmulatorStatus | null>(null);
  const [q, setQ] = useState<WhatIf>({ total_mm: 100, hours: 3, shape: "triangular_front", river_offset_m: 0 });
  const [res, setRes] = useState<EmulatorStats | null>(null);
  const [trig, setTrig] = useState<Triggers | null>(null);
  const [showAll, setShowAll] = useState(false);
  const timer = useRef<number>();

  useEffect(() => {  // status, polled while training
    let alive = true, t: number | undefined;
    const poll = () => getEmulator(aoiId).then((s) => {
      if (!alive) return;
      setSt(s);
      if (s.state === "queued" || s.state === "running") t = window.setTimeout(poll, 4000);
    }).catch(() => alive && setSt({ state: "none" }));
    poll();
    return () => { alive = false; window.clearTimeout(t); onPreview(null); };
  }, [aoiId]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (st?.state === "ready") getTriggers(aoiId).then(setTrig).catch(() => setTrig(null)); }, [st?.state, aoiId]);
  useEffect(() => {  // live prediction, debounced
    if (st?.state !== "ready") return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      predictEmulator(aoiId, q).then(setRes).catch(() => setRes(null));
      onPreview(emulatorPng(aoiId, q));
    }, 120);
  }, [q, st?.state, aoiId]);  // eslint-disable-line react-hooks/exhaustive-deps

  const set = (p: Partial<WhatIf>) => setQ((x) => ({ ...x, ...p }));
  const train = (force = false) => trainEmulator(aoiId, force).then((r) => { setSt({ state: r.state as EmulatorStatus["state"], progress: 0 }); snack("Training started. You can keep working; this takes about 10 minutes."); })
    .catch((e) => snack("Could not start: " + String(e.message)));

  if (!st) return <div className="shimmer" style={{ height: 200 }} />;
  if (st.state !== "ready") {
    const busy = st.state === "queued" || st.state === "running";
    return (
      <div className="stack">
        <div className="section-title"><Icon name="auto_awesome" /> AI what-if</div>
        <p className="body-m">Drag the rain and see the flood change instantly. An AI emulator learns this area's flood behaviour from many runs of the detailed 2D water model, then answers in milliseconds instead of a minute.</p>
        <p className="body-s muted">It also works out, for every village and neighbourhood, how much rain floods it: the rain triggers for early action.</p>
        {busy ? (
          <div className="card tonal stack-s">
            <span className="title-s">Training: {Math.round((st.progress ?? 0) * 100)}%</span>
            <Linear value={st.progress ?? 0} />
            <span className="body-s muted">Running {st.n_train ?? 64} storms through the 2D model, then checking the emulator on storms it has not seen. You can keep working.</span>
          </div>
        ) : (
          <>
            {st.state === "failed" && <div className="notice error"><Icon name="error" /><span>Training failed: {st.error}</span></div>}
            <Button icon="model_training" onClick={() => train(st.state === "failed")}>Train the AI emulator (about 10 minutes)</Button>
          </>
        )}
      </div>
    );
  }

  const v = st.validation;
  const maxTotal = Math.max(50, Math.round(st.range?.total_mm?.[1] ?? 300));
  const runThis = () => onRunThis({ rain_source: "manual", rain_preset: null, preset_label: null, manual_intensity_mm_h: Math.round((q.total_mm / q.hours) * 10) / 10,
    duration_h: q.hours, hyetograph: q.shape, river_offset_m: q.river_offset_m });
  const places = trig?.places ?? [];
  return (
    <div className="stack ai-panel">
      <div className="section-title"><Icon name="auto_awesome" /> AI what-if
        <HelpTip text={`${st.method}. Checked on ${v?.runs_inside_range ?? "?"} storms it had not seen: the flooded area overlaps the 2D model's by ${v?.csi_median != null ? Math.round(v.csi_median * 100) : "?"}% (median), depth error ${v?.mae_m_median != null ? Math.round(v.mae_m_median * 100) : "?"} cm.`} /></div>
      <Slider label="Rain" unit="mm" value={q.total_mm} min={5} max={maxTotal} step={5} onChange={(x) => set({ total_mm: x })} />
      <Slider label="Over" unit="h" value={q.hours} min={1} max={6} onChange={(x) => set({ hours: x })} />
      <Segmented label="Rain shape" block value={q.shape} onChange={(x) => set({ shape: x })}
        options={[{ value: "constant", label: "Steady" }, { value: "triangular_front", label: "Early peak" }]} />
      {!urban && <Slider label="River level above normal" unit="m" value={q.river_offset_m} min={0} max={3} step={0.5} onChange={(x) => set({ river_offset_m: x })} />}
      {res && (
        <div className="card tonal ai-res">
          <div className="row"><span className={`tag ${IMD_TAG[res.imd_category] ?? ""}`}>IMD {res.imd_category}</span><span className="grow" /><span className="body-s muted">answered in {res.ms < 1 ? "<1" : Math.round(res.ms)} ms</span></div>
          <dl className="ai-stats">
            <div><dt>People in water ≥ 30 cm</dt><dd>{nf(res.people_in_water)}</dd></div>
            <div><dt>Flooded area</dt><dd>{res.flooded_km2.toFixed(2)} km²</dd></div>
            <div><dt>Deepest water</dt><dd>{res.max_depth_m.toFixed(1)} m</dd></div>
          </dl>
          {res.outside_trained_range.length > 0 && <p className="body-s" style={{ margin: 0, color: "var(--error)" }}>Outside what the emulator was trained on; shown at the nearest trained storm. Run the full scenario.</p>}
          <p className="body-s muted" style={{ margin: 0 }}>Estimate of the 2D water model's peak flood. Routes, shelters and the brief need a full scenario.</p>
          <Button variant="tonal" icon="play_arrow" onClick={runThis}>Set up this storm as a full scenario</Button>
        </div>
      )}

      <div className="section-title" style={{ marginTop: 8 }}><Icon name="notifications_active" /> Rain triggers for early action
        <HelpTip text={`The smallest early-peaked storm that puts at least ${trig?.min_people ?? 25} people (or ${Math.round((trig?.share ?? 0.05) * 100)}% of residents) of a place in water ${Math.round((trig?.depth_m ?? 0.3) * 100)} cm deep or more at home. Computed with the 2D water model itself (${(trig as { method?: string } | null)?.method ?? "a sweep of storm sizes"}), not the emulator. ${trig?.note ?? ""}`} /></div>
      {!trig ? <div className="shimmer" style={{ height: 120 }} /> : !places.length ? <p className="body-s muted">No settlement floods within the trained storms.</p> : (
        <>
          <p className="body-s muted" style={{ margin: 0 }}>Rain (mm) that floods each place, if it falls within 1, 3 or 6 hours. Colour = the IMD 24-hour warning level that rain belongs to.</p>
          <table className="tbl ai-trig">
            <thead><tr><th>Place</th>{(trig.durations ?? [1, 3, 6]).map((h) => <th key={h} className="r">{h} h</th>)}</tr></thead>
            <tbody>{places.slice(0, showAll ? 60 : 8).map((pl) => (
              <tr key={pl.name + pl.lon} className="clickable" onClick={() => onFly(pl.lon, pl.lat)}>
                <td><span className="t">{pl.name}</span><span className="s">{nf(pl.residents)} residents</span></td>
                {(trig.durations ?? [1, 3, 6]).map((h) => {
                  const mm = pl.thresholds_mm[String(h)];
                  return <td key={h} className="r">{mm == null ? <span className="muted" title={`Not reached up to ${trig.max_trained_mm[String(h)]} mm`}>&gt;{trig.max_trained_mm[String(h)]}</span>
                    : <span className={`tag ${IMD_TAG[pl.imd[String(h)] ?? ""] ?? ""}`} title={`IMD ${pl.imd[String(h)]}`}>{mm}</span>}</td>;
                })}
              </tr>
            ))}</tbody>
          </table>
          {places.length > 8 && <Button variant="text" onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer" : `Show all ${places.length} places`}</Button>}
        </>
      )}
      <Button variant="text" icon="refresh" onClick={() => train(true)}>Retrain (after the area data changes)</Button>
    </div>
  );
}
