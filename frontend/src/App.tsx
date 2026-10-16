import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useMatch } from "react-router-dom";
import { getAoiStatus } from "./api/client";
import { authConfigured, signIn, signOut, useUser } from "./auth";
import Disclaimer from "./components/Disclaimer";
import { Icon, IconButton, Segmented, SnackbarProvider } from "./components/m3";
import { MapProvider } from "./components/MapCanvas";
import { setMode, useMode } from "./mode";

const names: Record<string, string> = {};

function Pill({ to, icon, label, end }: { to: string; icon: string; label: string; end?: boolean }) {
  return <NavLink end={end} to={to} className={({ isActive }) => `navpill sl ${isActive ? "active" : ""}`}><Icon name={icon} /><span className="lbl">{label}</span></NavLink>;
}

function Account() {
  const user = useUser();
  if (!authConfigured) return null;
  if (!user) return <button className="btn btn-outlined small sl" onClick={() => signIn().catch(() => undefined)}><Icon name="login" /> Sign in</button>;
  return (
    <span className="account" title={`${user.name} · ${user.email}`}>
      {user.photo ? <img src={user.photo} alt="" referrerPolicy="no-referrer" /> : <Icon name="account_circle" />}
      <IconButton icon="logout" label="Sign out" small onClick={() => signOut()} />
    </span>
  );
}

export default function App() {
  const area = useMatch("/area/:aoiId/*");
  const aoiId = area?.params.aoiId;
  const [name, setName] = useState<string>("");
  const mode = useMode();
  useEffect(() => {
    // the theme follows the operating system; clear the old manual override
    try { localStorage.removeItem("pravah-theme"); } catch { /* private mode */ }
    delete document.documentElement.dataset.theme;
  }, []);
  useEffect(() => {
    if (!aoiId) return;
    if (names[aoiId]) { setName(names[aoiId]); return; }
    getAoiStatus(aoiId).then((s) => { names[aoiId] = s.name ?? ""; setName(s.name ?? ""); }).catch(() => setName(""));
  }, [aoiId]);

  return (
    <MapProvider>
      <SnackbarProvider>
        <div className="app">
          <a href="#main" className="skip">Skip to content</a>
          <header className="topbar">
            <Link to="/" className="brand sl" aria-label="Pravah home">
              <img src="/pravah.svg" alt="" />
              <span className="name"><b>Pravah</b></span>
            </Link>
            {aoiId && (
              <>
                <span className="area-title"><Icon name="location_on" className="sm" />{name || "Area"}</span>
                <nav className="navpills" aria-label="Area">
                  {mode === "decision" ? (
                    <>
                      <Pill to={`/area/${aoiId}/advisory`} icon="assignment" label="Brief" />
                      <Pill end to={`/area/${aoiId}`} icon="map" label="Map" />
                      <Pill to={`/area/${aoiId}/verify`} icon="photo_camera" label="Field check" />
                    </>
                  ) : (
                    <>
                      <Pill end to={`/area/${aoiId}`} icon="map" label="Map" />
                      <Pill to={`/area/${aoiId}/advisory`} icon="assignment" label="Brief" />
                      <Pill to={`/area/${aoiId}/verify`} icon="photo_camera" label="Field check" />
                      <Pill to={`/area/${aoiId}/3d`} icon="view_in_ar" label="3D" />
                    </>
                  )}
                </nav>
              </>
            )}
            <span className="spacer" />
            <div className="mode-switch no-print" title="Decision view: the brief and the essentials. Analyst view: every control and technical layer.">
              <Segmented label="View" value={mode} onChange={setMode}
                options={[{ value: "decision", label: "Decision" }, { value: "analyst", label: "Analyst" }]} />
            </div>
            <Pill to="/methods" icon="menu_book" label="Methods" />
            <Account />
          </header>
          {aoiId && <Disclaimer className="global" />}
          <main id="main" className="page"><Outlet /></main>
        </div>
      </SnackbarProvider>
    </MapProvider>
  );
}
