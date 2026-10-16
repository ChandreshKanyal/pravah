// Decision view (default, for District Magistrates and SDMA officers) vs Analyst view (scenario controls, technical
// layers, 3D, chat). Stored per browser; components re-render on change.
import { useEffect, useState } from "react";

export type Mode = "decision" | "analyst";
const KEY = "pravah-mode";
const subs = new Set<(m: Mode) => void>();

function read(): Mode {
  try { return (localStorage.getItem(KEY) as Mode) === "analyst" ? "analyst" : "decision"; } catch { return "decision"; }
}

export function setMode(m: Mode) {
  try { localStorage.setItem(KEY, m); } catch { /* private mode */ }
  subs.forEach((f) => f(m));
}

export function useMode(): Mode {
  const [m, setM] = useState<Mode>(read);
  useEffect(() => { subs.add(setM); return () => { subs.delete(setM); }; }, []);
  return m;
}
