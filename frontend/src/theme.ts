// Light / dark / system theme (top-bar toggle). Stored per browser in localStorage "pravah-theme"; "system" (the default)
// follows the operating system through the prefers-color-scheme rules in styles.css. index.html applies a stored choice
// before the first paint; this module keeps <html data-theme>, the browser chrome colour and the Google map in step.
import { useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";
const KEY = "pravah-theme";
const SURFACE = { light: "#f8fafd", dark: "#131314" };  // --surface in each theme (styles.css)
const subs = new Set<(t: Theme) => void>();
const media = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

function read(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch { return "system"; }
}

let current: Theme = read();

function apply(t: Theme) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (t === "system") delete root.dataset.theme; else root.dataset.theme = t;
  // mobile address-bar colour follows an explicit choice; under "system" each tag keeps its own media query
  document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]').forEach((m) => {
    const own = m.media.includes("dark") ? "dark" : "light";
    m.content = SURFACE[t === "system" ? own : t];
  });
}
apply(current);

export function setTheme(t: Theme) {
  current = t;
  try { localStorage.setItem(KEY, t); } catch { /* private mode: the choice lasts for this page only */ }
  apply(t);
  subs.forEach((f) => f(t));
}

export function useTheme(): Theme {
  const [t, setT] = useState<Theme>(current);
  useEffect(() => { subs.add(setT); setT(current); return () => { subs.delete(setT); }; }, []);
  return t;
}

/** True when the page is dark: an explicit "dark", or "system" while the OS is in dark mode. */
export function useIsDark(): boolean {
  const t = useTheme();
  const [osDark, setOsDark] = useState(() => !!media?.matches);
  useEffect(() => {
    if (!media) return;
    const f = (e: MediaQueryListEvent) => setOsDark(e.matches);
    media.addEventListener("change", f);
    return () => media.removeEventListener("change", f);
  }, []);
  return t === "dark" || (t === "system" && osDark);
}
