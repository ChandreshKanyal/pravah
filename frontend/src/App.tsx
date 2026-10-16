import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useMatch } from "react-router-dom";
import { getAoiStatus } from "./api/client";
import Disclaimer from "./components/Disclaimer";
import { Icon, IconButton, SnackbarProvider } from "./components/m3";
import { MapProvider } from "./components/MapCanvas";

const names: Record<string, string> = {};

function useTheme(): ["light" | "dark" | null, () => void] {
  const [t, setT] = useState<"light" | "dark" | null>(() => {
    try { return (localStorage.getItem("pravah-theme") as "light" | "dark" | null) ?? null; } catch { return null; }
  });
  useEffect(() => {
    if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
    try { if (t) localStorage.setItem("pravah-theme", t); else localStorage.removeItem("pravah-theme"); } catch { /* private mode */ }
  }, [t]);
  const dark = t ? t === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  return [t, () => setT(dark ? "light" : "dark")];
}

export default function App() {
  const area = useMatch("/area/:aoiId/*");
  const aoiId = area?.params.aoiId;
  const [name, setName] = useState<string>("");
  const [theme, toggleTheme] = useTheme();
  useEffect(() => {
    if (!aoiId) return;
    if (names[aoiId]) { setName(names[aoiId]); return; }
    getAoiStatus(aoiId).then((s) => { names[aoiId] = s.name ?? ""; setName(s.name ?? ""); }).catch(() => setName(""));
  }, [aoiId]);
  const dark = theme ? theme === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;

  return (
    <MapProvider>
      <SnackbarProvider>
        <div className="app">
          <header className="topbar">
            <Link to="/" className="brand sl" aria-label="Pravah home">
              <img src="/pravah.svg" alt="" />
              <span className="name"><b>Pravah</b></span>
            </Link>
            {aoiId ? (
              <>
                <span className="area-title"><Icon name="location_on" className="sm" />{name || "Area"}</span>
                <nav className="navpills" aria-label="Area">
                  <NavLink end to={`/area/${aoiId}`} className={({ isActive }) => `navpill sl ${isActive ? "active" : ""}`}><Icon name="map" /><span className="lbl">Map</span></NavLink>
                  <NavLink to={`/area/${aoiId}/advisory`} className={({ isActive }) => `navpill sl ${isActive ? "active" : ""}`}><Icon name="assignment" /><span className="lbl">Advisory</span></NavLink>
                  <NavLink to={`/area/${aoiId}/verify`} className={({ isActive }) => `navpill sl ${isActive ? "active" : ""}`}><Icon name="photo_camera" /><span className="lbl">Verify</span></NavLink>
                  <NavLink to={`/area/${aoiId}/3d`} className={({ isActive }) => `navpill sl ${isActive ? "active" : ""}`}><Icon name="view_in_ar" /><span className="lbl">3D</span></NavLink>
                </nav>
              </>
            ) : null}
            <span className="spacer" />
            <span className="powered no-print" title="AI features run on Gemini via Vertex AI; data and compute on Google Cloud">
              <Icon name="auto_awesome" className="sm spark" /> Gemini · Google Cloud
            </span>
            <NavLink to="/methods" className={({ isActive }) => `navpill sl ${isActive ? "active" : ""}`}><Icon name="menu_book" /><span className="lbl">Methods</span></NavLink>
            <IconButton icon={dark ? "light_mode" : "dark_mode"} label={dark ? "Light theme" : "Dark theme"} onClick={toggleTheme} />
          </header>
          {aoiId && <Disclaimer className="global" />}
          <div className="page"><Outlet /></div>
        </div>
      </SnackbarProvider>
    </MapProvider>
  );
}
