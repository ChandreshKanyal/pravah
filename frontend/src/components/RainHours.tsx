// Hour-by-hour rain: the exact mm in each hour the model will use, filled automatically from the chosen source
// (forecast day, worst case, record, a past day's observed rain, IMD preset or custom) and editable per hour. Dragging
// a slider turns the scenario into an edited series (sent as rain_series_override); changing the source refills it.
import { useEffect, useRef, useState } from "react";
import { rainHours, type RainHours as RH } from "../api/client";
import { clockAt } from "../time";
import type { ScenarioParams } from "../types/api";
import { Button, Icon } from "./m3";

const BASE_KEYS = ["rain_source", "forecast_day_index", "worst_multiplier", "rain_preset", "manual_intensity_mm_h", "duration_h",
  "hyetograph", "observed_date"] as const;
const MAX_MM = 300;
const keyOf = (p: ScenarioParams) => JSON.stringify(BASE_KEYS.map((k) => (p as unknown as Record<string, unknown>)[k] ?? null));

export default function RainHours({ aoiId, p, set }: { aoiId: string; p: ScenarioParams; set: (patch: Partial<ScenarioParams>) => void }) {
  const [base, setBase] = useState<RH | null>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const editedAt = useRef<string | null>(p.rain_series_override ? keyOf(p) : null);
  const key = keyOf(p);

  useEffect(() => {  // refill from the source whenever a rain setting changes (an edit made for other settings is dropped)
    if (editedAt.current && editedAt.current !== key && p.rain_series_override) {
      editedAt.current = null;
      set({ rain_series_override: null, override_start_local: null, preset_label: null });
    }
    setLoading(true); setErr("");
    const t = window.setTimeout(() => {
      rainHours(aoiId, p).then((r) => { setBase(r); setLoading(false); }).catch((e) => { setErr(String((e as Error).message)); setLoading(false); });
    }, 250);
    return () => window.clearTimeout(t);
  }, [key, aoiId]);  // eslint-disable-line react-hooks/exhaustive-deps

  const H = Math.max(1, p.duration_h);
  const edited = !!p.rain_series_override;
  const vals = (p.rain_series_override ?? base?.series ?? []).slice(0, H);
  while (vals.length < H) vals.push(0);
  // bar scale: set from the rain itself, then fixed while dragging (a scale that followed the dragged value grew without
  // end and once sent 850 mm/h); letting go near the top widens it, up to 300 mm/h (about the world one-hour record)
  const nice = (v: number) => Math.min(MAX_MM, Math.max(20, Math.ceil((v * 1.6) / 10) * 10));
  const [scale, setScale] = useState<number | null>(null);
  useEffect(() => { setScale(null); }, [key]);
  const max = scale ?? nice(Math.max(...vals, 0));
  const grow = () => { if (Math.max(...vals, 0) >= 0.9 * max) setScale(Math.min(MAX_MM, max * 1.5)); else setScale(max); };
  const total = vals.reduce((a, b) => a + b, 0);
  const start = p.override_start_local ?? base?.start_local ?? null;

  const edit = (i: number, v: number) => {
    const next = vals.slice();
    next[i] = Math.min(MAX_MM, Math.max(0, Math.round(v * 10) / 10));
    if (scale == null) setScale(max);  // freeze the scale for this drag
    editedAt.current = key;
    set({ rain_series_override: next, override_start_local: base?.start_local ?? null,
      preset_label: `${(base?.label ?? "Rain").replace(/ \(edited by hand\)$/, "")} (edited by hand)` });
  };
  const reset = () => { editedAt.current = null; set({ rain_series_override: null, override_start_local: null, preset_label: null }); };

  return (
    <div className="rain-hours" aria-label="Rain in each hour">
      <div className="row nowrap">
        <span className="grow">
          <span className="label-m muted" style={{ display: "block" }}>Rain in each hour (mm){loading && " · updating…"}</span>
          <span className="title-s num">{total.toFixed(0)} mm in {H} h · peak {Math.max(...vals, 0).toFixed(0)} mm/h</span>
        </span>
        {edited ? <Button variant="text" size="small" icon="restart_alt" onClick={reset}>Reset</Button> : <span className="body-s muted">drag a bar to edit</span>}
      </div>
      <div className="rh-bars" style={{ ["--n" as string]: H }}>
        {vals.map((v, i) => (
          <label key={i} className="rh-col" title={`Hour ${i + 1}${clockAt(start, i + 1) ? ` (${clockAt(start, i + 1)})` : ""}: ${v.toFixed(1)} mm`}>
            <span className="rh-v">{v >= 10 ? Math.round(v) : v.toFixed(1)}</span>
            <span className="rh-track"><i style={{ height: `${Math.min(100, (v / max) * 100)}%` }} />
              <input type="range" min={0} max={max} step={0.5} value={Math.min(v, max)} onChange={(e) => edit(i, Number(e.target.value))}
                onPointerUp={grow} onKeyUp={grow}
                aria-label={`Hour ${i + 1} rain, mm`} /></span>
            <span className="rh-h">{H <= 12 || i % 2 === 0 ? (clockAt(start, i + 1)?.replace(/^.*?(\d{1,2}:\d{2}).*$/, "$1") ?? `${i + 1}h`) : ""}</span>
          </label>
        ))}
      </div>
      <p className="body-s muted" style={{ margin: 0 }}>
        {edited ? <b>Edited by hand</b> : (base?.label ?? "…")}
      </p>
      {err && <p className="body-s" style={{ margin: 0, color: "var(--error)" }}><Icon name="error" className="sm" /> {err}</p>}
      {!edited && base?.warnings?.map((w) => <p key={w} className="body-s" style={{ margin: 0, color: "var(--warning, #b06000)" }}>{w}</p>)}
    </div>
  );
}
