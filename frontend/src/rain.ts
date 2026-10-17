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
