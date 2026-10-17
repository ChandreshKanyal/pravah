// IMD rain presets for the Scenario chips (the hourly series itself comes from the backend: POST /api/aoi/{id}/rain-hours).
import type { ScenarioParams } from "./types/api";

export type RainPreset = NonNullable<ScenarioParams["rain_preset"]>;

/** mm in 24 h (top of each IMD band); cloudburst is the daily total whose wettest hour is 100 mm. */
export const PRESETS: { id: RainPreset; label: string; p24: number; note: string }[] = [
  { id: "imd_heavy", label: "IMD heavy", p24: 115.5, note: "64.5–115.5 mm/day (top of band used)" },
  { id: "imd_very_heavy", label: "IMD very heavy", p24: 204.4, note: "115.6–204.4 mm/day (top of band used)" },
  { id: "imd_extreme", label: "IMD extremely heavy", p24: 300, note: "≥ 204.5 mm/day (300 used)" },
  { id: "cloudburst", label: "Cloudburst", p24: 100 * Math.cbrt(24), note: "IMD: 100 mm in one hour" },
];

/** Short name of where the rain comes from, without numbers (a hand-edited run is named "<this>, edited by hand"; the
 * totals are added from the series itself, so the name never contradicts the hours). */
export function rainSourceName(p: ScenarioParams): string {
  const pr = p.rain_source === "manual" ? PRESETS.find((x) => x.id === p.rain_preset) : undefined;
  if (pr) return pr.label;
  if (p.rain_source === "manual") return "Your own rain";
  if (p.rain_source === "historical_extreme") return p.return_period_y ? `1-in-${p.return_period_y}-year rain` : "Record rain";
  if (p.rain_source === "observed") return p.observed_date ? `Rain of ${p.observed_date}` : "A past day's rain";
  return "Forecast rain";
}

/** Approximate world-record rain for a duration (mm): Jennings (1950) envelope P = 422 D^0.475, D in hours
 * (about 422 mm in 1 h, 1,200 mm in 9 h, 1,900 mm in 24 h). */
export const worldRecordMm = (hours: number) => 422 * Math.pow(Math.max(1, hours), 0.475);
