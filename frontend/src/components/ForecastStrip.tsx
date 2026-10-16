import { useState } from "react";
import type { Forecast } from "../types/api";
import { Icon, Tip } from "./m3";

const wx = (mm: number) => (mm >= 20 ? "thunderstorm" : mm >= 5 ? "rainy" : mm >= 0.5 ? "rainy_light" : mm > 0 ? "cloud" : "sunny");

/** 10-day screening strip (Google Weather style): day, icon, rain total and a screening badge bar. */
export default function ForecastStrip({ fc, selected, onPick }: { fc: Forecast | null; selected: number | null; onPick: (i: number) => void }) {
  const [open, setOpen] = useState(false);
  if (!fc) return <div className="fc-chip"><div className="shimmer" style={{ width: 200, height: 20 }} /></div>;
  const days = fc.screening.length ? fc.screening : fc.daily.map((d) => ({ ...d, max_stage_m: 0, badge: "low" as const }));
  if (!days.length) return <div className="fc-chip body-s muted">Forecast unavailable</div>;
  const total = days.reduce((a, d) => a + d.precip_mm, 0);
  const w = fc.worst_day_index ?? 0;
  const wd = days[w] ? new Date(days[w].date + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short" }) : "";
  const worstBadge = days.some((d) => d.badge === "high") ? "high" : days.some((d) => d.badge === "elevated") ? "elevated" : "low";
  const summary = total < 1 ? "Dry next 10 days" : `${total.toFixed(0)} mm in 10 days · wettest ${w === 0 ? "today" : wd} ${days[w].precip_mm.toFixed(0)} mm`;
  if (!open) return (
    <button className="fc-chip sl" onClick={() => setOpen(true)} aria-expanded={false} title="Show the 10-day forecast">
      <Icon name={wx(days[w]?.precip_mm ?? 0)} className="sm" /><span>{summary}</span>
      <span className={`fdot ${worstBadge}`} /><Icon name="expand_more" className="sm" />
    </button>
  );
  return (
    <div className="forecast" role="listbox" aria-label="10-day rain forecast">
      <button className="fc-close sl" onClick={() => setOpen(false)} aria-label="Collapse forecast"><Icon name="expand_less" /></button>
      {days.map((d, i) => {
        const dt = new Date(d.date + "T00:00:00");
        const label = i === 0 ? "Today" : dt.toLocaleDateString("en-IN", { weekday: "short" });
        return (
          <Tip key={d.date} below text={<>
            <b>{dt.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "short" })}</b><br />
            {d.precip_mm.toFixed(1)} mm forecast · screening: {d.badge} (main river {d.max_stage_m} m above base){fc.worst_day_index === i ? " · wettest day" : ""}
          </>}>
            <button role="option" aria-selected={selected === i} className={`fday sl ${selected === i ? "sel" : ""} ${fc.worst_day_index === i ? "worst" : ""}`} onClick={() => onPick(i)}>
              <span className="d">{label}</span>
              <Icon name={wx(d.precip_mm)} />
              <span className="mm">{d.precip_mm < 0.05 ? "0" : d.precip_mm.toFixed(1)} mm</span>
              <span className={`fbadge ${d.badge}`} />
            </button>
          </Tip>
        );
      })}
    </div>
  );
}
