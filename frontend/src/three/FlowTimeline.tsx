import { IconButton, Segmented } from "../components/m3";

export const RATES = { slow: 450, normal: 900, fast: 1800 } as const;  // model seconds per real second (1 h = 8 / 4 / 2 s)
export type Rate = keyof typeof RATES;

/** "2 h 35 min" from model seconds. */
export function span(t: number): string {
  const m = Math.floor(t / 60), h = Math.floor(m / 60);
  return h ? `${h} h ${String(m % 60).padStart(2, "0")} min` : `${m} min`;
}

/** Local clock time at model second t for forecast runs (start_local is the start of hour 1). */
export function clockOf(start: string | null | undefined, t: number): string | null {
  if (!start) return null;
  const d = new Date(start);
  if (Number.isNaN(d.getTime())) return null;
  d.setSeconds(d.getSeconds() + Math.round(t));
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** Continuous storm timeline for the 3D water: rain bars per hour under a scrubber, play/pause and speed. */
export default function FlowTimeline({ duration, time, setTime, playing, setPlaying, rate, setRate, rain, start, windowHour }: {
  duration: number; time: number; setTime: (t: number) => void; playing: boolean; setPlaying: (p: boolean) => void;
  rate: Rate; setRate: (r: Rate) => void; rain: number[]; start?: string | null; windowHour?: number | null;
}) {
  const hours = rain.length;
  const max = Math.max(1, ...rain);
  const hr = Math.min(hours - 1, Math.floor(time / 3600));
  const clock = clockOf(start, time);
  const cutT = windowHour ? (windowHour - 1) * 3600 : null;
  return (
    <div className="ftl" role="group" aria-label="Storm timeline">
      <IconButton icon={playing ? "pause" : time >= duration ? "replay" : "play_arrow"} label={playing ? "Pause" : "Play the storm"} variant="filled"
        onClick={() => { if (!playing && time >= duration) setTime(0); setPlaying(!playing); }} />
      <div className="track">
        <div className="bars" aria-hidden>
          {rain.map((r, i) => <span key={i} className={i <= hr ? "past" : ""}><i style={{ height: `${Math.max(8, 100 * (r / max))}%` }} /></span>)}
        </div>
        <div className="fill" style={{ width: `${(100 * time) / duration}%` }} />
        {cutT != null && cutT > 0 && cutT < duration && <div className="cut" style={{ left: `${(100 * cutT) / duration}%` }} title="Evacuation routes start to close" />}
        <input type="range" min={0} max={duration} step={60} value={Math.round(time)} aria-label="Time into the storm"
          aria-valuetext={`${span(time)} into the storm${clock ? `, ${clock}` : ""}`}
          onChange={(e) => { setPlaying(false); setTime(Number(e.target.value)); }} />
        <div className="ticks" aria-hidden>
          {Array.from({ length: hours + 1 }, (_, h) => (hours <= 12 || h % 3 === 0) && (
            <span key={h} style={{ left: `${(100 * h) / hours}%` }}>{clockOf(start, h * 3600) ?? `${h} h`}</span>
          ))}
        </div>
      </div>
      <div className="now">
        <span className="t num">{clock ?? span(time)}</span>
        <span className="s">{clock ? `${span(time)} into the storm` : "into the storm"} · <span className="num">{(rain[hr] ?? 0).toFixed(1)}</span> mm/h</span>
        {cutT != null && <span className={`cutnote ${time >= cutT ? "on" : ""}`}>{time >= cutT ? "Routes closing" : `Move before ${clockOf(start, cutT) ?? span(cutT)}`}</span>}
      </div>
      <Segmented label="Playback speed" value={rate} onChange={setRate}
        options={[{ value: "slow", label: "½×" }, { value: "normal", label: "1×" }, { value: "fast", label: "2×" }]} />
    </div>
  );
}
