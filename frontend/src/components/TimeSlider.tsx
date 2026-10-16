import { useEffect, useState } from "react";
import { clockAt, hourSpan } from "../time";
import { IconButton } from "./m3";

/** Bottom time bar (Google Weather hourly style): play/pause, one column per hour whose bar height is that hour's
 *  rain; hours up to the selected one are filled. Click a column or use the arrow keys to move. */
export default function TimeSlider({ hours, hour, setHour, rain, start, windowHour }: {
  hours: number; hour: number; setHour: (h: number) => void; rain: number[]; start?: string | null; windowHour?: number | null;
}) {
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setHour(hour >= hours ? 1 : hour + 1), 900);
    return () => clearInterval(t);
  }, [playing, hour, hours, setHour]);
  const max = Math.max(1, ...rain);
  const every = hours <= 12 ? 1 : hours <= 24 ? 3 : 6;  // label density
  return (
    <div className="timebar">
      <IconButton icon={playing ? "pause" : "play_arrow"} label={playing ? "Pause" : "Play hours"} variant="filled" onClick={() => setPlaying(!playing)} />
      <div className="hours" role="slider" tabIndex={0} aria-label="Hour" aria-valuemin={1} aria-valuemax={hours} aria-valuenow={hour}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight" || e.key === "ArrowUp") { e.preventDefault(); setHour(Math.min(hours, hour + 1)); }
          if (e.key === "ArrowLeft" || e.key === "ArrowDown") { e.preventDefault(); setHour(Math.max(1, hour - 1)); }
        }}>
        {Array.from({ length: hours }, (_, i) => {
          const h = i + 1, r = rain[i] ?? 0;
          return (
            <button key={h} tabIndex={-1} className={`hcol ${h <= hour ? "past" : ""} ${h === hour ? "cur" : ""} ${h === windowHour ? "cut" : ""}`} onClick={() => setHour(h)}
              title={`${hourSpan(start, h)}: ${r.toFixed(1)} mm/h${h === windowHour ? " · evacuation routes start to close" : ""}`}>
              <span className="bar"><i style={{ height: `${Math.max(6, 100 * (r / max))}%` }} /></span>
              <span className="lbl">{h === 1 || h === hours || h % every === 0 ? (clockAt(start, h) ?? `${h}h`) : ""}</span>
            </button>
          );
        })}
      </div>
      <span className="hour">{clockAt(start, hour) ? hourSpan(start, hour) : `Hour ${hour} of ${hours}`}<span className="muted num"> · {rain[hour - 1]?.toFixed(1) ?? "–"} mm/h</span>
        {windowHour ? <span className={`cutnote ${hour >= windowHour ? "on" : ""}`}>{hour >= windowHour ? "Routes closing" : `Move before ${clockAt(start, windowHour) ?? `hour ${windowHour}`}`}</span> : null}</span>
    </div>
  );
}
