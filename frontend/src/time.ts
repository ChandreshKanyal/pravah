// Scenario hours -> local clock times. Forecast runs carry start_local ("YYYY-MM-DDTHH:00", local time of hour 1);
// hypothetical rain has none, so hours are shown as "hour N after the rain starts".
export function clockAt(start: string | null | undefined, hour: number): string | null {
  if (!start) return null;
  const t = new Date(start);
  if (Number.isNaN(t.getTime())) return null;
  t.setHours(t.getHours() + Math.max(0, hour - 1));
  return t.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** "14:00–15:00" or "hour 3". */
export function hourSpan(start: string | null | undefined, hour: number): string {
  const a = clockAt(start, hour), b = clockAt(start, hour + 1);
  return a && b ? `${a}–${b}` : `hour ${hour}`;
}

/** Deadline for an hour: "before 03:00 (hour 4)" or "before hour 4". */
export function before(start: string | null | undefined, hour: number | null | undefined): string {
  if (hour == null) return "";
  const c = clockAt(start, hour);
  if (hour <= 1) return c ? `before the rain starts (${c})` : "before the rain starts";
  return c ? `before ${c} (hour ${hour})` : `before hour ${hour}`;
}

export const roundPeople = (n: number) => { const s = n < 100 ? 5 : n < 1000 ? 10 : n < 10000 ? 50 : 100; return Math.round(n / s) * s; };
