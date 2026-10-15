import { useEffect, useState } from "react";
import { IconButton, Slider } from "./m3";

/** Bottom time bar: play/pause, hour slider and the hourly rain profile. */
export default function TimeSlider({ hours, hour, setHour, rain }: { hours: number; hour: number; setHour: (h: number) => void; rain: number[] }) {
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setHour(hour >= hours ? 1 : hour + 1), 900);
    return () => clearInterval(t);
  }, [playing, hour, hours, setHour]);
  const max = Math.max(1, ...rain);
  return (
    <div className="timebar">
      <IconButton icon={playing ? "pause" : "play_arrow"} label={playing ? "Pause" : "Play hours"} variant="filled" onClick={() => setPlaying(!playing)} />
      <div className="grow stack-s" style={{ gap: 0 }}>
        <div className="rainbars" aria-hidden>{rain.map((r, i) => <i key={i} className={i < hour ? "on" : ""} style={{ height: `${10 + 90 * (r / max)}%` }} title={`${r.toFixed(1)} mm/h`} />)}</div>
        {hours > 1 ? <Slider label="" value={hour} min={1} max={hours} onChange={setHour} format={() => ""} />
          : <div style={{ height: 44 }} />}
      </div>
      <div className="stack-s" style={{ gap: 0, alignItems: "flex-end" }}>
        <span className="hour">Hour {hour} / {hours}</span>
        <span className="body-s muted num">{rain[hour - 1]?.toFixed(1) ?? "–"} mm/h</span>
      </div>
    </div>
  );
}
