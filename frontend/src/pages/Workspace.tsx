import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMap } from "@vis.gl/react-google-maps";
import type { Layer, PickingInfo } from "@deck.gl/core";
import { createRun, setRunMeta, getAoiStatus, getForecast, getGeoJson, getImprovements, getRun, getStaticLayers, refreshImprovements } from "../api/client";
import PrepThinking from "../components/PrepThinking";
import ChoiceCard, { type Choice } from "../components/ChoiceCard";
import ImprovementsPanel from "../components/ImprovementsPanel";
import { reportRun, takePendingCommand, type AppCommand } from "../components/Assistant";
import DrawControl, { type DrawMode } from "../components/DrawControl";
import ForecastStrip from "../components/ForecastStrip";
import AiPanel from "../components/AiPanel";
import CompareRuns from "../components/CompareRuns";
import HistoryPanel from "../components/HistoryPanel";
import LayerPanel, { SHADE_FAMILY, type LayerKey } from "../components/LayerPanel";
import { Button, Dialog, Field, Icon, Linear, Tabs, nf, useSnackbar } from "../components/m3";
import MapLegend, { type SymKey } from "../components/MapLegend";
import { AreaOutline, CameraWatch, MapCanvas, StreetViewAt, StreetViewWatch, ZoomWatch, type Camera, type MapType } from "../components/MapCanvas";
import Results, { niceName } from "../components/Results";
import ScenarioPanel from "../components/ScenarioPanel";
import TimeSlider from "../components/TimeSlider";
import { RASTER, REASON, areaLayers, bitmap, overlayUrl, deckLine, markers, polygonsLayer, roadState, roadsLayers, routeClosed, routesLayer } from "../layers/factories";
import { clockAt } from "../time";
import { defaultParams, type AoiStatus, type Forecast, type HistoryAoi, type Improvement, type ImprovementCategory, type Improvements, profileOf, type RunResult, type ScenarioParams, type StaticLayers } from "../types/api";

// what a decision needs at a glance: where the water is, which roads close, where people go. Hospitals, assembly and
// staging points, drains and stream hotspots are one switch away in Layers (and listed in Results).
/** What the background "fix before the rain" job is doing (its steps run after the area opens). */
function impStep(steps?: Record<string, string | null>): string {
  // the satellite checks (clogged) and the road graph (congested) run side by side, then the analytics step
  if (steps?.clogged === "ready" && steps?.congested === "ready") return "Running analytics…";
  if (steps?.congested === "ready") return "Finding clogged drains…";
  if (steps?.clogged === "ready") return "Finding congested roads…";
  return "Finding clogged drains and congested roads…";
}

/** Order-independent key of scenario settings (the panel vs the run on the map). */
const pkey = (o: object) => JSON.stringify(Object.entries(o).sort(([x], [y]) => x.localeCompare(y)));

/** Short name of the storm a run simulates, for the map's what-if label. */
function scenLabel(r: RunResult): string {
  const total = Math.round(r.rain_series_mm_h.reduce((a, b) => a + b, 0)), H = r.rain_series_mm_h.length;
  const src = r.params.rain_source as string;
  const T = r.params.return_period_y;
  // runs saved before 17 Oct froze the source's numbers into a hand-edited name ("50 mm/h ... for 4 h (edited by hand)"),
  // which could contradict the hours run: keep only the source's name
  const pl = r.params.preset_label?.endsWith("(edited by hand)") ? `${r.params.preset_label.split(":")[0].replace(/ \(edited by hand\)$/, "")}, edited by hand` : r.params.preset_label;
  const name = r.title || pl || (src === "historical_extreme" && T ? `1-in-${T}-year rain` : null) || ({ forecast: "forecast rain", worst: "worst-case forecast", best: "best-case forecast",
    historical_extreme: "record rain", observed: "a past day's rain", manual: "custom rain" } as Record<string, string>)[src] || "scenario";
  const k = r.params.rain_scale ?? 1;
  const scaled = Math.abs(k - 1) > 0.001 && (r.rain_label ?? "").includes("(not the actual");  // applied, not a fallback
  return `${name}${scaled ? ` × ${k.toFixed(2)}` : ""}, ${total} mm in ${H} h`;
}

const DEFAULT_LAYERS: LayerKey[] = ["depth", "roads", "routes", "shelters", "bridges"];

// what the preparation screen says, in the order the backend does it (prepare_area.py): each stage is done when all of
// its steps are; keys an older area never ran are ignored when absent
const STAGES: { label: string; sub: string; keys: string[] }[] = [
  { label: "Downloading terrain data", sub: "Copernicus elevation, MERIT Hydro rivers", keys: ["terrain", "hydro30"] },
  { label: "Gathering weather and flood history", sub: "rainfall climate, past floods, surface water since 1984", keys: ["hazard_hist", "landcover"] },
  { label: "Analysing the road network", sub: "OpenStreetMap roads, bridges and distances", keys: ["osm", "derived"] },
  { label: "Estimating population", sub: "WorldPop and Google Open Buildings", keys: ["population", "buildings", "building_proxy"] },
  { label: "Gathering infrastructure", sub: "shelters, hospitals, bridges, routes", keys: ["network"] },
  { label: "Analysing flood risk", sub: "stream network, flood susceptibility, waterlogging hollows", keys: ["hydrology", "overlays", "fsi", "urban"] },
];

function FlyTo({ target }: { target: { lon: number; lat: number; zoom?: number; t: number } | null }) {
  const map = useMap();
  useEffect(() => {
    if (map && target) { map.panTo({ lat: target.lat, lng: target.lon }); if (target.zoom) map.setZoom(target.zoom); }
  }, [map, target]);
  return null;
}

function Traffic({ on }: { on: boolean }) {
  const map = useMap();
  useEffect(() => {
    if (!map || !on) return;
    const t = new google.maps.TrafficLayer(); // display only; never read into the engine
    t.setMap(map);
    return () => t.setMap(null);
  }, [map, on]);
  return null;
}

type Tab = "scenario" | "results" | "ai" | "compare" | "history";

// the Map page's working state for this visit (tab session): settings, layers, tab, hour, shown run and camera, so a
// trip to 3D, the brief or the drill comes back to the same picture
type Snap = { p: ScenarioParams; on: LayerKey[]; tab: Tab; hour: number; mapType: MapType; runId: string | null; shown: boolean; cam?: Camera };
const snapKey = (aoiId: string) => `pravah:ws:${aoiId}`;
function readSnap(aoiId: string): Snap | null {
  try { const v = sessionStorage.getItem(snapKey(aoiId)); return v ? (JSON.parse(v) as Snap) : null; } catch { return null; }
}
function writeSnap(aoiId: string, s: Snap) { try { sessionStorage.setItem(snapKey(aoiId), JSON.stringify(s)); } catch { /* private mode: not kept */ } }

/** Fetch every hour's overlay up front, so moving the time slider swaps a ready picture instead of loading one. */
function usePreloaded(urls: string[] | null): (ImageBitmap | null)[] {
  const [imgs, setImgs] = useState<(ImageBitmap | null)[]>([]);
  const key = urls?.join("|") ?? "";
  useEffect(() => {
    setImgs([]);
    if (!urls?.length) return;
    let alive = true;
    urls.forEach((u, i) => fetch(overlayUrl(u)).then((r) => (r.ok ? r.blob() : Promise.reject())).then((b) => createImageBitmap(b))
      .then((im) => { if (alive) setImgs((cur) => { const n = cur.slice(); n[i] = im; return n; }); }).catch(() => undefined));
    return () => { alive = false; };
  }, [key]);  // eslint-disable-line react-hooks/exhaustive-deps
  return imgs;
}
/** The frame for this hour, or the nearest earlier one already loaded (never a blank). */
const frameAt = (imgs: (ImageBitmap | null)[], i: number) => { for (let k = i; k >= 0; k--) if (imgs[k]) return imgs[k]; return null; };

export default function Workspace() {
  const { aoiId = "" } = useParams();
  const [search] = useSearchParams();
  const runParam = search.get("run");  // a saved run opened from Projects or a shared link
  const nav = useNavigate();
  const [, setSearch] = useSearchParams();
  const snack = useSnackbar();
  const snap = useRef(readSnap(aoiId)).current;
  const restored = useRef(false);  // the saved state is applied (until then nothing is saved over it)
  const cam = useRef<Camera | undefined>(snap?.cam);
  const [status, setStatus] = useState<AoiStatus | null>(null);
  const [st, setSt] = useState<StaticLayers | null>(null);
  const [fc, setFc] = useState<Forecast | null>(null);
  const [p, setP] = useState<ScenarioParams>(() => (snap?.p ? { ...defaultParams(aoiId), ...snap.p } : defaultParams(aoiId)));
  const [aiPng, setAiPng] = useState<string | null>(null);
  const [runName, setRunName] = useState("");  // optional experiment name, saved with the run (Projects)
  const [run, setRun] = useState<RunResult | null>(null);
  const [prev, setPrev] = useState<RunResult | null>(null);
  const [roads, setRoads] = useState<GeoJSON.FeatureCollection | null>(null);
  const [routes, setRoutes] = useState<GeoJSON.FeatureCollection | null>(null);
  const [hist, setHist] = useState<HistoryAoi | null>(null);
  const [hour, setHour] = useState(snap?.hour ?? 1);
  const [zoom, setZoom] = useState(13);
  const labels = zoom >= 15;  // ids (S12, A3, D1...) only at street zoom; at area zoom they pile on top of each other
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drawMode, setDrawMode] = useState<DrawMode>(null);
  const [fly, setFly] = useState<{ lon: number; lat: number; zoom?: number; t: number } | null>(null);
  const [tab, setTab] = useState<Tab>(snap?.tab ?? "scenario");
  const [fitT, setFitT] = useState(0);
  const [mapType, setMapType] = useState<MapType>(snap?.mapType ?? "hybrid");
  const [pending, setPending] = useState<{ lng: number; lat: number } | null>(null);
  const [cap, setCap] = useState("200");
  const [on, setOn] = useState<Set<LayerKey>>(() => new Set(snap?.on ?? DEFAULT_LAYERS));
  // "Fix before the rain" (pre-monsoon improvements): computed at the end of area preparation
  const [imp, setImp] = useState<Improvements | null>(null);
  const [impOpen, setImpOpen] = useState(() => search.get("fixes") === "1");  // ?fixes=1 opens the list (shareable)
  const [impSel, setImpSel] = useState<Improvement | null>(null);
  const [impCats, setImpCats] = useState<Set<ImprovementCategory> | null>(null);
  const [sv, setSv] = useState<{ lon: number; lat: number; t: number } | null>(null);
  const [choice, setChoice] = useState<Choice | null>(null);  // the shelter or route whose details card is open
  const [svOn, setSvOn] = useState(false);     // Street View open: our overlays step aside and "Back to map" shows
  const [svClose, setSvClose] = useState(0);
  useEffect(() => {  // Esc also leaves Street View
    if (!svOn) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") setSvClose(Date.now()); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [svOn]);
  const shown = on;

  const set = useCallback((patch: Partial<ScenarioParams>) => setP((x) => ({ ...x, ...patch })), []);
  // the panel no longer matches the run on the map (keys sorted so field order does not matter)
  const changed = useMemo(() => {
    if (!run) return false;
    return pkey({ ...defaultParams(aoiId), ...run.params }) !== pkey(p);
  }, [run, p, aoiId]);
  // the scenario is drawn only for a run made or opened in this visit; until then roads are live (Google traffic)
  const [shownRun, setShownRun] = useState<string | null>(null);
  const pRef = useRef(p);
  pRef.current = p;
  const live = !run || shownRun !== run.run_id;
  const runRef = useRef<string | null>(null);
  runRef.current = run?.run_id ?? null;
  const save = useCallback(() => {
    if (!restored.current) return;
    writeSnap(aoiId, { p, on: [...on], tab, hour, mapType, runId: run?.run_id ?? null, shown: !live, cam: cam.current });
  }, [aoiId, p, on, tab, hour, mapType, run, live]);
  useEffect(save, [save]);
  const onCam = useCallback((c: Camera) => { cam.current = c; save(); }, [save]);
  // the run on the map goes in the link, so 3D, the brief and the drill open this run too
  useEffect(() => {
    if (!run || live || runParam === run.run_id) return;
    setSearch((q) => { const n = new URLSearchParams(q); n.set("run", run.run_id); return n; }, { replace: true });
  }, [run, live]);  // eslint-disable-line react-hooks/exhaustive-deps
  const depthImgs = usePreloaded(run && !live && on.has("depth") ? run.depth_png_urls : null);
  // switching on a shaded layer switches off the others drawn with the same colours (blues: water; yellow-red: susceptibility)
  const toggle = (k: LayerKey) => setOn((s) => {
    const n = new Set(s);
    if (n.has(k)) { n.delete(k); return n; }
    n.add(k);
    const fam = SHADE_FAMILY[k];
    if (fam) for (const o of Object.keys(SHADE_FAMILY) as LayerKey[]) if (o !== k && SHADE_FAMILY[o] === fam) n.delete(o);
    return n;
  });
  const ready = status?.state === "ready" || status?.state === "partial";
  const onFly = useCallback((lon: number, lat: number) => setFly({ lon, lat, zoom: 16, t: Date.now() }), []);

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const s = await getAoiStatus(aoiId);
        if (stop) return;
        setStatus(s);
        if (s.state !== "ready" && s.state !== "partial") setTimeout(tick, 3000);
      } catch (e) { if (!stop) setError(String((e as Error).message)); }
    };
    tick();
    return () => { stop = true; };
  }, [aoiId]);

  // improvements: load when the area is ready; areas prepared before this feature compute them now (1-2 minutes)
  useEffect(() => {
    if (!ready) return;
    let stop = false, asked = false;
    const tick = async () => {
      try {
        const d = await getImprovements(aoiId);
        if (stop) return;
        if (d.state === "none" && !asked) { asked = true; await refreshImprovements(aoiId).catch(() => null); setImp({ state: "running" }); setTimeout(tick, 4000); return; }
        setImp(d);
        const want = search.get("fix");  // ?fix=I3 opens that item (shareable link to one place)
        if (want && d.items) { const it = d.items.find((x) => x.id === want); if (it) { setImpOpen(true); setImpSel(it); setFly({ lon: it.lon, lat: it.lat, zoom: 17, t: Date.now() }); } }
        if (d.state === "running") setTimeout(tick, 5000);
      } catch { if (!stop) setImp(null); }
    };
    tick();
    return () => { stop = true; };
  }, [aoiId, ready]);

  const loadRun = useCallback(async (r: RunResult, keepPrev = true, keepPanel = false) => {
    setRun((cur) => { if (keepPrev && cur && cur.run_id !== r.run_id) setPrev(cur); return r; });
    if (!keepPanel) {
      const np = { ...defaultParams(aoiId), ...r.params };
      // runs saved before the hour editor was fixed can hold impossible hand edits (850 mm/h): start from the source again
      if (np.rain_series_override?.some((v) => v > 300)) Object.assign(np, { rain_series_override: null, override_start_local: null, preset_label: null });
      setP(np);
    }
    setHour(1);  // a run opens at its first hour, so the flood is seen building up (back from 3D restores the hour left)
    const [rd, rt] = await Promise.all([
      r.roads_geojson_url ? getGeoJson(r.roads_geojson_url).catch(() => null) : Promise.resolve(null),
      r.routes_geojson_url ? getGeoJson(r.routes_geojson_url).catch(() => null) : Promise.resolve(null),
    ]);
    setRoads(rd);
    setRoutes(rt);
  }, [aoiId]);

  useEffect(() => {
    if (!ready) return;
    getStaticLayers(aoiId).then((s) => {
      setSt(s);
    }).catch((e) => setError(String(e.message)));
    getForecast(aoiId, p.duration_h).then(setFc).catch(() => setFc(null));
    const rid = runParam || snap?.runId || status?.latest_run_id;
    if (rid && rid === runRef.current) { if (runParam) setShownRun(rid); restored.current = true; return; }  // already open (URL caught up)
    if (!rid) { restored.current = true; return; }
    getRun(rid).then(async (r) => {
      // back from 3D or the brief: the panel and hour as left; a different run opened from a link takes its own settings
      const same = !!snap && (snap.runId === r.run_id || snap.runId == null);
      await loadRun(r, false, same);
      if (same && snap!.runId === r.run_id) setHour(Math.min(Math.max(1, snap!.hour), r.rain_series_mm_h.length));
      if (runParam || (same && snap!.shown)) setShownRun(r.run_id);
    }).catch(() => undefined).finally(() => { restored.current = true; });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, aoiId, runParam]);

  // auto = the map updating itself after the settings change: quiet, no 3D water model, keeps edits made meanwhile
  async function doRun(auto = false, params?: ScenarioParams) {
    const sent = params ?? p, sentKey = pkey(sent);
    setRunning(true);
    setError(null);
    try {
      const r = await createRun(sent, { flow: !auto });
      if (!auto && runName.trim()) { await setRunMeta(r.run_id, { title: runName.trim() }).catch(() => undefined); r.title = runName.trim(); setRunName(""); }
      // settings edited while it ran: show this result but keep the panel, so the next automatic run picks the edits up
      await loadRun(r, true, pkey(pRef.current) !== sentKey);
      setShownRun(r.run_id);
      if (!auto) {
        setTab("results");
        snack(r.capacity_gap_people > 0 ? `Done: ${nf(r.people_to_evacuate)} people to move, ${nf(r.capacity_gap_people)} without a place` : `Done: ${nf(r.people_to_evacuate)} people to move, all placed`,
          { label: "Brief", onClick: () => nav(`/area/${aoiId}/run/${r.run_id}/advisory`) });
      }
    } catch (e) {
      setError(String((e as Error).message));
      snack("The scenario could not run: " + String((e as Error).message));
    } finally { setRunning(false); }
  }

  // commands from the assistant (confirmed by the user in the chat): run a scenario, switch layers, open the fixes list
  const command = (cmd: AppCommand) => {
    if (cmd.type === "run") {
      // the same rules as the Scenario panel and the backend (models/scenario.apply_rain_change): a new source starts as
      // its actual data, an explicit hyetograph is the shape, and hand edits for the old rain are dropped
      const rainKeys = ["rain_source", "rain_preset", "manual_intensity_mm_h", "forecast_day_index", "worst_multiplier", "duration_h", "hyetograph", "observed_date", "return_period_y"];
      const ks = Object.keys(cmd.patch);
      const reset: Partial<ScenarioParams> = ks.some((k) => rainKeys.includes(k)) ? { rain_series_override: null, override_start_local: null, preset_label: null } : {};
      if (ks.some((k) => ["rain_source", "rain_preset", "manual_intensity_mm_h", "observed_date"].includes(k)) && !ks.includes("rain_scale")) reset.rain_scale = 1;
      if (ks.includes("rain_source") && !ks.includes("return_period_y")) reset.return_period_y = null;
      if (ks.includes("hyetograph")) reset.rain_shape = (cmd.patch as Partial<ScenarioParams>).hyetograph;
      else if (ks.some((k) => ["rain_source", "rain_preset"].includes(k)) && !ks.includes("rain_shape")) reset.rain_shape = null;
      const np = { ...p, ...cmd.patch, ...reset } as ScenarioParams;
      setP(np);
      setTab("scenario");
      if (!running) doRun(false, np);
    } else {
      setOn((cur) => {
        const n = new Set(cur);
        for (const k of cmd.off ?? []) n.delete(k as LayerKey);
        for (const k of cmd.on ?? []) n.add(k as LayerKey);
        return n;
      });
      if (cmd.fixes) { setImpOpen(true); setImpSel(null); }
    }
  };
  useEffect(() => {
    const h = (e: Event) => command((e as CustomEvent<AppCommand>).detail);
    window.addEventListener("pravah:command", h);
    return () => window.removeEventListener("pravah:command", h);
  });
  useEffect(() => {  // a command sent before this map was open runs once the area is ready
    if (!ready || !st) return;
    const cmd = takePendingCommand(aoiId);
    if (cmd) command(cmd);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, st, aoiId]);
  useEffect(() => { reportRun(run?.run_id ?? null); return () => reportRun(null); }, [run]);
  useEffect(() => setChoice(null), [run?.run_id, live]);

  // layers, plus a count of every legend symbol they draw, so the legend shows exactly what is on the map at this hour
  const { layers, drawn } = useMemo(() => {
    const L: Layer[] = [];
    const drawn: Partial<Record<SymKey, number>> = {};
    const add = (k: SymKey, n = 1) => { if (n > 0) drawn[k] = (drawn[k] ?? 0) + n; };
    const on = shown;
    const area = status?.bbox ? areaLayers(status.bbox) : null;
    if (area) { L.push(area.mask); add("area"); }
    if (!st) { if (area) L.push(...area.border); return { layers: L, drawn }; }
    if (impOpen && imp?.items) {  // the improvements view shows alone: the box and the numbered places to fix
      if (area) L.push(...area.border);
      const items = imp.items.filter((it) => !impCats || impCats.has(it.category));
      L.push(...markers("imp", items, { icon: "fix", size: (it) => (impSel?.id === it.id ? 30 : 20), trigger: impSel?.id,
        label: (it) => it.id.slice(1) }));
      add("fix", items.length);
      return { layers: L, drawn };
    }
    const c = st.corners;
    const box = status?.bbox ?? null;  // everything the model counts is inside the box: cut shading and roads there
    const statics = [["fsi", "fsi"], ["hand", "hand"], ["crowd", "crowdShade"], ["streams", "stream"]] as const;
    for (const [k, sym] of statics) {
      if (on.has(k) && st.layers[k]) { L.push(bitmap(`static-${k}`, st.layers[k], c, RASTER[k].opacity, box)); add(sym); }
    }
    const aiOn = tab === "ai" && !!aiPng;  // the AI preview replaces the run's flood while the tab is open
    if (aiOn) { L.push(bitmap("ai-preview", aiPng!, c, RASTER.depth.opacity, box)); add("depth"); }
    if (live && on.has("roads")) add("traffic");  // live view: Google traffic in place of scenario roads
    if (run && !aiOn && !live) {  // the AI preview shows alone: the run's routes and markers belong to a different storm
      const oc = run.overlay_corners.length ? run.overlay_corners : c;
      // one layer per run (not per hour), fed preloaded frames: the water grows smoothly instead of flashing
      if (on.has("depth") && run.depth_png_urls[hour - 1]) { L.push(bitmap(`depth-${run.run_id}`, run.depth_png_urls[hour - 1], oc, RASTER.depth.opacity, box, frameAt(depthImgs, hour - 1))); add("depth"); add("water"); }
      if (on.has("ponding") && run.ponding_png_url) { L.push(bitmap(`pond-${run.run_id}`, run.ponding_png_url, oc, RASTER.ponding.opacity, box)); add("ponding"); }
      if (on.has("roads") && roads) {
        L.push(...roadsLayers("roads", roads, hour, box));
        const sym = { open: "roadOpen", later: "roadLater", closed: "roadClosed" } as const;
        for (const f of roads.features) {
          const s = roadState(f.properties?.first_closed_hour, hour), cut = (f.properties?.hazard?.length ?? 0) > 0;
          add(sym[s]);
          if (cut && s === "closed") add("roadCut");
        }
      }
      if (on.has("routes") && routes) {
        L.push(routesLayer("routes", routes, hour));
        for (const f of routes.features) add(routeClosed(f.properties?.passable_until_h, hour) ? "routeClosed" : "route");
      }
      if (on.has("drains") && run.drains?.length) { L.push(...markers("drains", run.drains, { icon: "drain", size: 18, label: labels ? (d) => d.id : undefined })); add("drain", run.drains.length); }
      if (on.has("bridges")) {
        // only bridges that close get a marker; the rest stay open (listed in Results) and would bury the map in dots
        // and only inside the box: closures in the hydrology buffer are not counted anywhere
        const closing = run.bridges.filter((b) => b.first_closed_hour != null
          && (!box || (b.lon >= box[0] && b.lon <= box[2] && b.lat >= box[1] && b.lat <= box[3])));
        L.push(...markers("bridges", closing, { icon: (b) => (b.first_closed_hour! <= hour ? "bridgeClosed" : "bridgeLater"), size: 18, trigger: hour }));
        for (const b of closing) add(b.first_closed_hour! <= hour ? "bridgeClosed" : "bridgeLater");
      }
      if (on.has("assembly")) { L.push(...markers("assembly", run.assembly_points, { icon: "assembly", size: 18, label: labels ? (a) => a.id : undefined })); add("assembly", run.assembly_points.length); }
      if (on.has("staging")) { L.push(...markers("staging", run.staging_points, { icon: "staging", size: 20, label: labels ? (s) => s.id : undefined })); add("staging", run.staging_points.length); }
    }
    // hospitals win over clinics where markers would overlap; zoom in to see the rest (hundreds in a city)
    if (on.has("medical")) {
      const med = box ? st.medical.filter((m) => m.lon >= box[0] && m.lon <= box[2] && m.lat >= box[1] && m.lat <= box[3]) : st.medical;
      L.push(...markers("medical", med, { icon: "medical", size: med.length > 30 ? 14 : 17, declutter: { priority: (m) => (m.kind === "hospital" ? 1 : 0), spacing: 2.6 } }));
      add("medical", med.length);
    }
    // shelters: by default only those people are sent to (sized by places filled); every candidate is one switch away.
    // Before a run nothing is in use yet, so candidates keep the candidate marker.
    type Pt = { id: string; name: string; lon: number; lat: number; assigned: number; capacity: number; status?: string; place?: string };
    const cand: Pt[] = run ? run.shelters.filter((s) => s.kind !== "assembly_point") : st.shelters.map((s) => ({ ...s, assigned: 0, capacity: 0 }));
    const rest = run ? cand.filter((s) => s.assigned === 0) : cand;
    if (on.has("all_shelters") || (!run && on.has("shelters"))) {
      L.push(...markers("shelters-all", rest, { icon: "candidate", size: rest.length > 60 ? 13 : 15, label: labels ? (s) => s.id : undefined,
        declutter: rest.length > 40 ? { spacing: 1.6 } : undefined }));
      add("candidate", rest.length);
    }
    if (run && !aiOn && !live && on.has("shelters")) {
      const used = cand.filter((s) => s.assigned > 0);
      L.push(...markers("shelters", used, { icon: "shelter", size: (s) => 16 + 10 * Math.min(1, s.assigned / Math.max(1, s.capacity)), label: labels ? (s) => s.id : undefined,
        declutter: { priority: (s) => s.assigned, spacing: 1.2 } }));
      add("shelter", used.length);
    }
    if (on.has("streams")) { L.push(...markers("hotspots", st.hotspots.slice(0, 8), { icon: "hotspot", size: 15 })); add("hotspot", Math.min(8, st.hotspots.length)); }
    if (on.has("crowd")) { L.push(...markers("crowdhs", st.crowd_hotspots, { icon: "crowd", size: 15, label: labels ? (x) => x.id : undefined })); add("crowd", st.crowd_hotspots.length); }
    if (on.has("history") && hist && run) {  // reported incidents only alongside a scenario's results
      const web = (hist.web ?? []).filter((w) => w.marker).map((w) => ({ lon: w.marker!.lng, lat: w.marker!.lat, label: w.date.slice(0, 4), w }));
      L.push(...markers("hist-web", web, { icon: "webReport", size: 15, label: (w) => w.label }));
      add("webReport", web.length);
    }
    if (on.has("traffic")) add("traffic");
    if (p.blocked_polygons.length) { L.push(polygonsLayer("blocked", p.blocked_polygons)); add("blocked"); }
    if (p.extra_shelters.length) {
      L.push(...markers("extra", p.extra_shelters.map((s) => ({ ...s, lon: s.lng })), { icon: "shelter", size: 22, label: (s) => s.name }));
      add("userShelter", p.extra_shelters.length);
    }
    if (changed && run && !live) {  // the panel no longer matches this run: fade its results so they do not read as current
      const RUN = /^(depth-|pond-|roads|routes|drains|bridges|assembly|staging|shelters$|shelters-label)/;
      for (let k = 0; k < L.length; k++) if (RUN.test(L[k].id)) L[k] = L[k].clone({ opacity: 0.3 * ((L[k].props as any).opacity ?? 1) });
    }
    if (area) {
      // border above the rasters but below roads and points: insert after the last bitmap layer
      let i = 0; L.forEach((x, k) => { if (/^(area-mask|static-|depth-|pond-)/.test(x.id)) i = k + 1; });
      L.splice(i, 0, ...area.border);
    }
    return { layers: L, drawn };
  }, [status?.bbox, st, run, roads, routes, hour, depthImgs, shown, p.blocked_polygons, p.extra_shelters, hist, tab, aiPng, labels, impOpen, imp, impCats, impSel, changed, live]);

  // hover text uses the legend's words (open / closes later / closed) so the map, the key and Results agree
  const tooltip = useCallback((info: PickingInfo): string | null => {
    const o = info.object as any, id = info.layer?.id ?? "";
    const at = (h: number) => { const c = clockAt(run?.start_local, h); return c ? `${c} (hour ${h})` : `hour ${h}`; };
    const why = (r?: string | null) => (r ? ` · ${REASON[r] ?? r}` : "");
    const shelterName = (sid: string) => { const s = run?.shelters.find((x) => x.id === sid); return s ? `${sid} ${niceName(s)}` : sid; };
    switch (id) {
      case "imp": return `${o.id.slice(1)}. ${o.title}${o.place ? `\n${o.place}` : ""}\nClick for the evidence`;
      case "roads": {
        const q = o.p, s = roadState(q.first_closed_hour, hour), name = (q.name || "Unnamed road") + (q.bridge ? " (bridge)" : "");
        const where = o.piece ? " here" : "";
        if (o.cut && !o.piece && s !== "open") return s === "later" ? `${name}\nOpen; blocked further along from ${at(q.first_closed_hour)}${why(q.reason)} (in this scenario)`
          : `${name}\nNo through road since ${at(q.first_closed_hour)}: blocked further along${why(q.reason)} (in this scenario)`;
        return s === "open" ? `${name}\nRoad open all scenario`
          : s === "later" ? `${name}\nLikely blocked${where} from ${at(q.first_closed_hour)}${why(q.reason)} (in this scenario)`
            : `${name}\nLikely blocked${where} since ${at(q.first_closed_hour)}${why(q.reason)} (in this scenario)`;
      }
      case "routes": {
        const q = o.p, h = q.passable_until_h as number | null;
        const state = h == null ? "Open all scenario" : routeClosed(h, hour) ? `Route closed since ${at(h)}: a road on it closed` : `Open now, closes at ${at(h)}`;
        return `Evacuation route to ${shelterName(q.to_shelter)}\n${q.people} people · ${q.eta_min} min\n${state}`;
      }
      case "bridges":
        return `${o.id} ${o.name}\n${o.first_closed_hour <= hour ? `Bridge closed since ${at(o.first_closed_hour)}` : `Bridge closes later: at ${at(o.first_closed_hour)}`}${why(o.reason)}${deckLine(o) ? `\n${deckLine(o)}` : ""}`;
      case "shelters": return `${o.id} ${niceName(o)}\nShelter in use · ${o.assigned} of ${o.capacity} places`;
      case "shelters-all": {
        const note: Record<string, string> = { flooded: "flooded", disabled: "closed by you", unreachable: "unreachable" };
        return `${o.id} ${niceName(o)}\n${run ? "Candidate shelter, not used" : "Candidate shelter"}${o.status && note[o.status] ? ` · ${note[o.status]}` : ""}`;
      }
      case "extra": return `${o.name}\nShelter you added · ${o.capacity} places, used from the next run`;
      case "assembly": return `${o.id} · Assembly point\nRoom for about ${o.capacity} people`;
      case "staging": return `${o.id} · Staging point for response teams${o.reason ? `\n${o.reason}` : ""}`;
      case "medical": return `${o.name || "Hospital or clinic"}\n${o.kind === "clinic" ? "Clinic" : "Hospital"}`;
      case "drains": return `${o.id} ${o.name || o.type}\nDrain to inspect · priority ${o.priority.toFixed(2)} · ${o.exposed_people_300m} people within 300 m`;
      case "hotspots": return `Flow hotspot ${o.id}\n${o.type}, ${Math.round(o.upa_km2).toLocaleString("en-IN")} km² drains here`;
      case "crowdhs": return `Crowding hotspot ${o.id}${o.top_attractors?.length ? `\n${o.top_attractors.slice(0, 2).join(" · ")}` : ""}`;
      case "hist-web": return `Web report · ${o.w.date}${o.w.place ? ` · ${o.w.place}` : ""}`;
      case "blocked": return "Area you blocked\nRoads inside are closed from hour 1 of the next run";
      default: return null;
    }
  }, [hour, run]);

  // the "move before" hour is the first route cut, or else the first bridge closure (backend _evac_window): say which
  const cutLabel = useMemo(() => {
    if (!run) return undefined;
    if ((routes?.features ?? []).some((f) => routeClosed(f.properties?.passable_until_h, hour))) return "Some routes closed";
    if (run.bridges.some((b) => b.first_closed_hour != null && b.first_closed_hour <= hour && b.reason === "overtopped")) return "Bridges closed";
    return "Roads closing";
  }, [run, routes, hour]);

  const usedShelters = useMemo(() => new Set((run?.shelters ?? []).filter((x) => x.assigned > 0).map((x) => x.id)), [run]);
  // a stage is done when each of its steps is ready (or was never part of this area's run, e.g. "urban" for river areas)
  const stageState = (keys: string[]) => {
    const st = status?.status ?? {};
    const present = keys.filter((k) => k in st);
    if (present.some((k) => st[k] === "error")) return "err";
    if (present.length && present.every((k) => st[k] === "ready")) return "done";
    return "todo";
  };
  const doneStages = STAGES.filter((g) => stageState(g.keys) === "done").length;
  const activeStage = STAGES.findIndex((g) => stageState(g.keys) === "todo");
  const onPick = useCallback((info: PickingInfo) => {
    const id = info.layer?.id ?? "", o = info.object as any;
    if (id === "imp") { const it = o as Improvement; setImpSel(it); setFly({ lon: it.lon, lat: it.lat, zoom: Math.max(zoom, 16), t: Date.now() }); return; }
    // a shelter or route of the shown run: its checks and Gemini's explanation (ChoiceCard)
    if (run && !live && o && ["shelters", "shelters-all", "assembly"].includes(id) && o.id) { setImpOpen(false); setChoice({ kind: "shelter", id: o.id }); return; }
    if (run && !live && o && id === "routes" && o.p?.to_shelter) { setImpOpen(false); setChoice({ kind: "route", key: `${o.p.from_node}-${o.p.to_shelter}` }); }
  }, [zoom, run, live]);
  const impItems = imp?.items ?? [];
  const days = fc?.daily.map((d, i) => (i === 0 ? "Today" : new Date(d.date + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric" }))) ?? [];
  const onHist = useCallback((h: HistoryAoi) => { setHist(h); }, []);

  return (
    <div className="workspace">
      <aside className="ws-panel" aria-label="Scenario and results">
        <Tabs value={tab} onChange={setTab} withIcons tabs={[
          { value: "scenario", label: "Scenario", icon: "tune" },
          { value: "results", label: "Results", icon: "insights", badge: run && run.capacity_gap_people > 0 ? "!" : undefined },
          { value: "ai", label: "What-if", icon: "auto_awesome" },
          { value: "compare", label: "Compare", icon: "compare_arrows" },
          { value: "history", label: "History", icon: "history" },
        ]} />
        {running ? <Linear indeterminate /> : <div style={{ height: 4 }} />}
        <div className="panel-body">
          {!ready && (status ? <PrepThinking stages={STAGES} stateOf={stageState} name={status.name} />
            : <div className="stack-s"><div className="shimmer" style={{ height: 120 }} /><div className="shimmer" style={{ height: 200 }} /></div>)}
          {ready && st && tab === "scenario" && profileOf(status) && (
            <p className="area-profile body-s" title={`Built-up ${Math.round(100 * profileOf(status)!.built_share)}% · median slope ${profileOf(status)!.slope_p50}° · largest river catchment ${profileOf(status)!.largest_river_km2.toLocaleString("en-IN")} km² (worked out from the data; no mode)`}>
              <Icon name="travel_explore" className="sm" />{profileOf(status)!.summary}</p>
          )}
          {ready && st && tab === "scenario" && (
            <ScenarioPanel p={p} set={set} replace={setP} shelters={st.shelters} drawMode={drawMode} setDrawMode={setDrawMode} days={days} used={usedShelters} past={fc?.past_90d}
              drain={status?.drain} onDrain={(d) => setStatus((s) => (s ? { ...s, drain: d } : s))}
              waterlogging={profileOf(status)?.hazards.includes("waterlogging") ?? status?.mode === "urban"} />
          )}
          {ready && tab === "results" && (run ? <Results run={run} hour={hour} onFly={onFly} previous={prev} onChoose={(c) => { setImpOpen(false); setChoice(c); }} /> : (
            <div className="stack" style={{ alignItems: "center", textAlign: "center", padding: "48px 16px" }}>
              <Icon name="insights" className="xl muted" />
              <p className="title-m">No results yet</p>
              <p className="body-m muted">Set up the rain and press Run scenario. Try “Record” for the wettest day on record.</p>
              <Button variant="tonal" icon="tune" onClick={() => setTab("scenario")}>Open scenario</Button>
            </div>
          ))}
          {ready && tab === "compare" && <CompareRuns aoiId={aoiId} currentId={run?.run_id ?? null}
            onOpen={(id) => getRun(id).then((r) => { loadRun(r); setShownRun(r.run_id); setTab("results"); }).catch((e) => snack(String(e.message)))} />}
          {ready && tab === "history" && <HistoryPanel aoiId={aoiId} onFly={onFly} onData={onHist} />}
          {ready && tab === "ai" && <AiPanel aoiId={aoiId} urban={profileOf(status) ? !profileOf(status)!.hazards.includes("river") : status?.mode === "urban"} onPreview={setAiPng} onFly={onFly}
            onRunThis={(patch) => { set(patch); setTab("scenario"); snack("Storm set up. Press Run scenario for routes, shelters and the brief."); }} />}
          {ready && status?.warnings?.length && tab === "scenario" ? (
            <details className="card tonal">
              <summary className="row" style={{ cursor: "pointer", listStyle: "none" }}><Icon name="info" /><span className="title-s grow">Area data notes ({status.warnings.length})</span><Icon name="expand_more" /></summary>
              <ul className="body-s" style={{ margin: "8px 0 0", paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }}>{status.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </details>
          ) : null}
          {error && ready && <div className="notice error"><Icon name="error" /><span>{error}</span></div>}
          {changed && tab === "scenario" && !running && <div className="notice"><Icon name="info" /><span>Settings changed since the run on the map. Press Run scenario to update the map, brief and 3D.</span></div>}
        </div>
        <div className="panel-foot">
          {tab === "results" && run ? (
            <div className="row nowrap">
              <Button variant="outlined" icon="replay" onClick={() => setTab("scenario")}>Edit scenario</Button>
              <Button className="grow" icon="assignment" onClick={() => nav(`/area/${aoiId}/run/${run.run_id}/advisory`)}>View advisory brief</Button>
            </div>
          ) : (
            <>
            {tab === "scenario" && <input className="run-name" value={runName} onChange={(e) => setRunName(e.target.value)} maxLength={120}
              placeholder="Name this run (optional), e.g. “Bypass closed, 2 schools opened”" aria-label="Run name" />}
            <Button block size="lg" icon={running ? undefined : "play_arrow"} disabled={!ready || running} onClick={() => doRun(false)}>
              {running ? <><span className="spinner small" style={{ borderTopColor: "currentColor" }} /> Running scenario, about a minute…</> : "Run scenario"}
            </Button>
            </>
          )}
        </div>
      </aside>

      <main className={`ws-map ${svOn ? "sv-on" : ""}`}>
        <MapCanvas center={snap?.cam ? { lat: snap.cam.lat, lng: snap.cam.lng } : { lat: 30.28, lng: 78.98 }} zoom={snap?.cam?.zoom ?? 12} layers={layers} mapTypeId={mapType} tooltip={tooltip} onPick={onPick}>
          <FlyTo target={fly} />
          <StreetViewAt target={sv} onNone={() => snack("Google has no Street View within 1 km of this spot. Try Look closer for satellite.")}
            onFound={(m) => { if (m > 60) snack(`Nearest Street View is about ${m >= 1000 ? "1 km" : `${Math.round(m / 10) * 10} m`} from the spot, looking towards it`); }} />
          <StreetViewWatch onChange={setSvOn} closeT={svClose} />
          <ZoomWatch onZoom={setZoom} />
          <CameraWatch onChange={onCam} />
          <AreaOutline bbox={status?.bbox} fitKey={fitT} keepView={!!snap?.cam} padding={{ top: 64, right: 200, bottom: 88, left: 32 }} />
          <Traffic on={on.has("traffic") || (live && on.has("roads") && !impOpen)} />
          <DrawControl mode={drawMode}
            onFinish={(poly) => { setDrawMode(null); set({ blocked_polygons: [...p.blocked_polygons, poly] }); snack("Road block added. Run the scenario to reroute."); }}
            onPoint={(lng, lat) => { setDrawMode(null); setPending({ lng, lat }); }} />
        </MapCanvas>

        {svOn && (
          <button className="sv-back sl" onClick={() => setSvClose(Date.now())}>
            <Icon name="arrow_back" /> Back to map
          </button>
        )}

        <div className="top">
          <ForecastStrip fc={fc} selected={["forecast", "worst", "best"].includes(p.rain_source) ? p.forecast_day_index : null}
            onPick={(i) => { set({ forecast_day_index: i, rain_source: ["worst", "best"].includes(p.rain_source) ? p.rain_source : "forecast" }); setTab("scenario"); }} />
          {status?.official?.imd_warning && (
            <span className={`imd-badge ${status.official.imd_warning}`} title={`Entered by ${status.official.entered_by ?? ""}`}>IMD {status.official.imd_warning}</span>
          )}
          {imp && imp.state !== "error" && (imp.state === "running" || impItems.length > 0) && (
            <button className={`fc-chip sl imp-chip ${impOpen ? "on" : ""} ${imp.state === "ready" && !impOpen ? "pulse" : ""}`}
              disabled={imp.state !== "ready"} onClick={() => { setImpOpen(!impOpen); setImpSel(null); if (!impOpen) setFitT(Date.now()); }}
              title="Places where maintenance would most reduce flooding">
              {imp.state === "running" ? <><span className="spinner small" /> {impStep(imp.steps)}</>
                : <><Icon name="build" className="sm" /> {impItems.length} fixes</>}
            </button>
          )}
          {!impOpen && tab !== "ai" && (running ? (
            <span className="fc-chip scen-chip stale" role="status"><span className="spinner small" style={{ borderTopColor: "currentColor" }} />Running scenario…</span>
          ) : live ? (
            <span className="fc-chip live-chip" title="Roads show Google live traffic (display only). Run a scenario to see its closures, flooding and routes.">
              <span className="dot" />Live roads
              {run && <button className="btn btn-text small sl" onClick={() => setShownRun(run.run_id)} title={`Show the last run: ${scenLabel(run)}`}>Show last run</button>}
            </span>
          ) : changed ? (
            <span className="fc-chip scen-chip stale" title={`Showing ${scenLabel(run!)}; press Run scenario for your new settings`}>
              <Icon name="history" className="sm" />Last run · Run to update
              <button className="btn btn-text small sl" onClick={() => setShownRun(null)}>Live</button>
            </span>
          ) : (
            <span className="fc-chip scen-chip" data-tour="scen-chip" title="Roads, water and routes are this simulated storm, not live conditions">
              <Icon name="science" className="sm" />What-if: {scenLabel(run!)}
              <button className="btn btn-text small sl" onClick={() => setShownRun(null)} title="Back to live roads">Live</button>
            </span>
          ))}
          {status?.bbox && (
            <button className="fc-chip icon-only sl" onClick={() => setFitT(Date.now())} title={`Zoom to ${status.name ?? "the simulated area"}`} aria-label="Zoom to the simulated area">
              <Icon name="center_focus_strong" className="sm" />
            </button>
          )}
        </div>

        {drawMode && (
          <div className="draw-hint" style={{ top: 112 }} role="status">
            <Icon name={drawMode === "point" ? "add_home" : "block"} />
            {drawMode === "point" ? "Click the map where the shelter is" : "Click points around the road to block; double-click to finish"}
            <button className="btn btn-text sl" onClick={() => setDrawMode(null)}>Cancel</button>
          </div>
        )}

        {impOpen && imp?.state === "ready" && (
          <ImprovementsPanel data={imp} selected={impSel} cats={impCats} setCats={setImpCats}
            onSelect={(it) => { setImpSel(it); if (it) setFly({ lon: it.lon, lat: it.lat, zoom: Math.max(zoom, 16), t: Date.now() }); }}
            onClose={() => { setImpOpen(false); setImpSel(null); }}
            onLook={(it) => { setMapType("hybrid"); setFly({ lon: it.lon, lat: it.lat, zoom: 19, t: Date.now() }); }}
            onStreetView={(it) => setSv({ lon: it.lon, lat: it.lat, t: Date.now() })} />
        )}

        {choice && run && !live && !impOpen && (
          <ChoiceCard run={run} choice={choice} className="map-choice" onClose={() => setChoice(null)}
            routes={(routes?.features ?? []).map((f) => f.properties as Record<string, any>)} />
        )}

        {!impOpen && !choice && <MapLegend drawn={drawn} hasRun={!!run && !live} when={run && !live ? (clockAt(run.start_local, hour) ? `${clockAt(run.start_local, hour)} · hour ${hour}` : `hour ${hour}`) : undefined} />}

        <div className="bottom">
          <LayerPanel on={on} toggle={toggle} hasRun={!!run} mapType={mapType} setMapType={setMapType} urban={profileOf(status)?.hazards.includes("waterlogging") ?? status?.mode === "urban"} />
          {run && !live && tab !== "ai" && !impOpen ? <TimeSlider hours={run.rain_series_mm_h.length} hour={hour} setHour={setHour} rain={run.rain_series_mm_h} start={run.start_local} windowHour={run.evac_window_h} cutLabel={cutLabel} /> : <span className="spacer" />}
          <span style={{ width: 72 }} />
        </div>

        {!ready && (
          <div className="prepare surface-float stack" role="status">
            <div className="row nowrap"><span className="spinner" /><div className="grow"><div className="title-l">Preparing {status?.name ?? "area"}</div>
              <div className="body-s muted">About 3–5 minutes for a new area, up to 10 for a large dense city. You can leave this page open.</div></div></div>
            <Linear value={doneStages / STAGES.length} />
            <ul className="steps">
              {STAGES.map((g, i) => {
                const st = stageState(g.keys), active = i === activeStage;
                return <li key={g.label} className={st === "done" ? "done" : st === "err" ? "err" : active ? "active" : ""}>
                  {active ? <span className="spinner small" /> : <Icon name={st === "done" ? "check_circle" : st === "err" ? "error" : "radio_button_unchecked"} className="sm" fill={st === "done"} />}
                  <span>{g.label}{active && <span className="body-s muted" style={{ display: "block" }}>{g.sub}</span>}</span></li>;
              })}
            </ul>
            {error && <div className="notice error"><Icon name="error" />{error}</div>}
          </div>
        )}
      </main>


      <Dialog open={!!pending} title="Add a shelter" icon="add_home" onClose={() => setPending(null)}
        actions={<>
          <Button variant="text" onClick={() => setPending(null)}>Cancel</Button>
          <Button onClick={() => {
            const n = Number(cap);
            if (pending && n > 0) {
              const k = p.extra_shelters.length + 1;
              set({ extra_shelters: [...p.extra_shelters, { id: `U${k}`, name: `User shelter ${k}`, lat: pending.lat, lng: pending.lng, capacity: n }] });
              snack(`Shelter U${k} added. Run the scenario to use it.`);
            }
            setPending(null);
          }}>Add</Button>
        </>}>
        <div className="stack">
          <p className="body-m muted">A school, hall or building the authorities can open. It is used from the next run.</p>
          <Field label="Capacity (people)" support="Roughly floor area × floors × 0.6 ÷ 3.5 m² per person">
            <input type="number" min={1} value={cap} autoFocus onChange={(e) => setCap(e.target.value)} />
          </Field>
        </div>
      </Dialog>
    </div>
  );
}
