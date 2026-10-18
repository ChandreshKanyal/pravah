import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useMatch } from "react-router-dom";
import { getAoiStatus, renameAoi } from "./api/client";
import { authConfigured, signIn, signOut, useUser } from "./auth";
import Disclaimer from "./components/Disclaimer";
import { Icon, IconButton, Segmented, SnackbarProvider } from "./components/m3";
import { MapProvider } from "./components/MapCanvas";
import Assistant from "./components/Assistant";
import { setTheme, useTheme, type Theme } from "./theme";

const names: Record<string, string> = {};

/** The open area's name in the top bar; click to rename it (Enter or leaving the field saves, Esc cancels). */
function AreaTitle({ aoiId, name, onRenamed }: { aoiId: string; name: string; onRenamed: (n: string) => void }) {
  const [edit, setEdit] = useState<string | null>(null);
  const [err, setErr] = useState(false);
  const done = useRef(false);
  const save = async () => {
    if (done.current || edit == null) return;
    done.current = true;
    const n = edit.trim();
    if (!n || n === name) { setEdit(null); return; }
    try { onRenamed((await renameAoi(aoiId, n)).name); setEdit(null); }
    catch { setErr(true); done.current = false; }
  };
  if (edit != null) return (
    <span className="area-title editing">
      <Icon name="location_on" className="sm" />
      <input autoFocus value={edit} maxLength={80} aria-label="Area name" className={err ? "err" : ""}
        onFocus={(e) => e.currentTarget.select()} onChange={(e) => { setEdit(e.target.value); setErr(false); }} onBlur={save}
        onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") { done.current = true; setEdit(null); } }} />
    </span>
  );
  return (
    <button className="area-title sl" title="Rename this area" onClick={() => { done.current = false; setErr(false); setEdit(name); }}>
      <Icon name="location_on" className="sm" />{name || "Area"}<Icon name="edit" className="sm area-edit" />
    </button>
  );
}

function Pill({ to, icon, label, end }: { to: string; icon: string; label: string; end?: boolean }) {
  return <NavLink end={end} to={to} className={({ isActive }) => `navpill sl ${isActive ? "active" : ""}`}><Icon name={icon} /><span className="lbl">{label}</span></NavLink>;
}

const THEMES: { value: Theme; label: string; icon: string }[] = [
  { value: "light", label: "Light", icon: "light_mode" },
  { value: "dark", label: "Dark", icon: "dark_mode" },
  { value: "system", label: "System default", icon: "contrast" },
];

/** Day/night switch: an icon button with a small Material menu (Light, Dark, System default). At phone width the same
 *  menu opens from a "more" button and also holds Methods, so the top bar fits 360-390 px. */
function ThemeMenu() {
  const theme = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  const cur = THEMES.find((t) => t.value === theme) ?? THEMES[2];
  return (
    <div ref={ref} className={`menu-anchor no-print ${open ? "open" : ""}`}>
      <span className="wide-only"><IconButton icon={cur.icon} label={`Theme: ${cur.label}`} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} /></span>
      <span className="phone-only"><IconButton icon="more_vert" label="Theme and Methods" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} /></span>
      {open && (
        <div className="menu" role="menu" aria-label="Theme">
          <div className="menu-label">Theme</div>
          {THEMES.map((t) => (
            <button key={t.value} role="menuitemradio" aria-checked={theme === t.value} className="menu-item sl" autoFocus={theme === t.value}
              onClick={() => { setTheme(t.value); setOpen(false); }}>
              <Icon name={t.icon} /><span className="grow">{t.label}</span>{theme === t.value && <Icon name="check" className="chk" />}
            </button>
          ))}
          <div className="phone-only"><hr /><Link to="/methods" role="menuitem" className="menu-item sl" onClick={() => setOpen(false)}><Icon name="menu_book" /><span className="grow">Methods</span></Link></div>
        </div>
      )}
    </div>
  );
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
  // a run other than the area's default (opened from Projects or a shared link) stays open across Brief, Map and 3D
  const loc = useLocation();
  const runRoute = useMatch("/area/:aoiId/run/:runId/*");
  const runId = new URLSearchParams(loc.search).get("run") ?? runRoute?.params.runId ?? null;
  const q = runId ? `?run=${runId}` : "";
  const [name, setName] = useState<string>("");
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
                <AreaTitle aoiId={aoiId} name={name} onRenamed={(n) => { names[aoiId] = n; setName(n); }} />
                <nav className="navpills" aria-label="Area">
                  <Pill to={runId ? `/area/${aoiId}/run/${runId}/advisory` : `/area/${aoiId}/advisory`} icon="assignment" label="Brief" />
                  <Pill end to={`/area/${aoiId}${q}`} icon="map" label="Map" />
                  <Pill to={`/area/${aoiId}/3d${q}`} icon="view_in_ar" label="3D" />
                  <Pill to={`/area/${aoiId}/drill${q}`} icon="sports_score" label="Drill" />
                  <Pill to={`/area/${aoiId}/verify`} icon="photo_camera" label="Field check" />
                </nav>
              </>
            )}
            <span className="spacer" />
            <Pill to="/projects" icon="folder_open" label="Projects" />
            <span className="wide-only"><Pill to="/methods" icon="menu_book" label="Methods" /></span>
            <ThemeMenu />
            <Account />
          </header>
          {aoiId && <Disclaimer className="global" />}
          <main id="main" className="page"><Outlet /></main>
        </div>
        <Assistant />
      </SnackbarProvider>
    </MapProvider>
  );
}
