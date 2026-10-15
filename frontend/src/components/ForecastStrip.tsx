import type { Forecast } from "../types/api";
import { Icon, Tip } from "./m3";

const wx = (mm: number) => (mm >= 20 ? "thunderstorm" : mm >= 5 ? "rainy" : mm >= 0.5 ? "rainy_light" : mm > 0 ? "cloud" : "sunny");

/** 10-day screening strip (Google Weather style): day, icon, rain total and a screening badge bar. */
export default function ForecastStrip({ fc, selected, onPick }: { fc: Forecast | null; selected: number | null; onPick: (i: number) => void }) {
  if (!fc) return <div className="forecast"><div className="shimmer" style={{ width: 560, height: 70 }} /></div>;
  const days = fc.screening.length ? fc.screening : fc.daily.map((d) => ({ ...d, max_stage_m: 0, badge: "low" as const }));
  if (!days.length) return <div className="forecast body-s muted" style={{ padding: 12 }}>Forecast unavailable</div>;
  return (
    <div className="forecast" role="listbox" aria-label="10-day rain forecast">
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
