import { useEffect, useState } from "react";

export default function TimeSlider({ hours, hour, setHour, rain }: { hours: number; hour: number; setHour: (h: number) => void; rain: number[] }) {
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setHour(hour >= hours ? 1 : hour + 1), 900);
    return () => clearInterval(t);
  }, [playing, hour, hours, setHour]);
  return (
    <div className="timeslider card">
      <button onClick={() => setPlaying(!playing)} aria-label={playing ? "Pause" : "Play"}>{playing ? "❚❚" : "▶"}</button>
      <input type="range" min={1} max={hours} value={hour} onChange={(e) => setHour(Number(e.target.value))} aria-label="Hour" />
      <span>Hour <b>{hour}</b> / {hours}</span>
      <span className="muted tiny">rain {rain[hour - 1]?.toFixed(1) ?? "-"} mm/h</span>
    </div>
  );
}
