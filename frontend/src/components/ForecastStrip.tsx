import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Forecast } from "../types/api";

const BADGE = { low: "badge-low", elevated: "badge-elev", high: "badge-high" } as const;

export default function ForecastStrip({ fc, selected, onPick }: { fc: Forecast | null; selected: number | null; onPick: (i: number) => void }) {
  if (!fc) return <div className="strip muted">Loading forecast…</div>;
  const days = fc.screening.length ? fc.screening : fc.daily.map((d) => ({ ...d, max_stage_m: 0, badge: "low" as const }));
  const past = fc.past_90d.filter((d) => d.precip_mm != null);
  return (
    <div className="strip">
      <div className="days" role="list" aria-label="10-day forecast screening">
        {days.map((d, i) => {
          const dt = new Date(d.date + "T00:00:00");
          return (
            <button key={d.date} role="listitem" className={`day ${selected === i ? "sel" : ""} ${fc.worst_day_index === i ? "worst" : ""}`}
              onClick={() => onPick(i)} title={`Screening max stage ${d.max_stage_m} m`}>
              <span className="dname">{dt.toLocaleDateString("en-IN", { weekday: "short", day: "numeric" })}</span>
              <span className="mm">{d.precip_mm.toFixed(1)} mm</span>
              <span className={`badge ${BADGE[d.badge]}`}>{d.badge}</span>
            </button>
          );
        })}
      </div>
      <div className="past">
        <div className="tiny muted">Past 90 days, daily rain (mm), {fc.past_90d.length ? "GPM IMERG" : "unavailable"}</div>
        <ResponsiveContainer width="100%" height={52}>
          <BarChart data={past} margin={{ top: 2, right: 2, bottom: 0, left: 0 }}>
            <XAxis dataKey="date" hide />
            <YAxis width={28} tick={{ fontSize: 9 }} />
            <Tooltip formatter={(v) => [`${v} mm`, "Rain"]} />
            <Bar dataKey="precip_mm" fill="#3182bd" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="tiny muted strip-note">{fc.screening_note} {fc.attribution}.</div>
    </div>
  );
}
