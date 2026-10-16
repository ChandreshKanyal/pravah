import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMap } from "@vis.gl/react-google-maps";
import type { Layer } from "@deck.gl/core";
import { createRun, getAoiStatus, getForecast, getGeoJson, getRun, getStaticLayers } from "../api/client";
import ChatPanel from "../components/ChatPanel";
import DrawControl, { type DrawMode } from "../components/DrawControl";
import ForecastStrip from "../components/ForecastStrip";
import HistoryPanel from "../components/HistoryPanel";
import LayerPanel, { type LayerKey } from "../components/LayerPanel";
import { Button, Dialog, Fab, Field, Icon, Linear, Tabs, nf, useSnackbar } from "../components/m3";
import MapLegend from "../components/MapLegend";
import { AreaOutline, MapCanvas, type MapType } from "../components/MapCanvas";
import Results from "../components/Results";
import ScenarioPanel from "../components/ScenarioPanel";
import TimeSlider from "../components/TimeSlider";
import { COLORS, areaLayers, bitmap, points, polygonsLayer, roadsLayer, routesLayer } from "../layers/factories";
import { defaultParams, type AoiStatus, type Forecast, type HistoryAoi, type RunResult, type ScenarioParams, type StaticLayers } from "../types/api";

const STEPS: [string, string][] = [["terrain", "Terrain"], ["hydro30", "Rivers"], ["landcover", "Land cover"], ["hazard_hist", "Past hazards"],
  ["population", "Population"], ["buildings", "Buildings"], ["osm", "Roads & places"], ["derived", "Road distance"], ["hydrology", "Stream network"],
  ["overlays", "Map overlays"], ["fsi", "Flood susceptibility"], ["lsi", "Landslide susceptibility"], ["building_proxy", "Building classes"], ["network", "Routes & shelters"]];

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

type Tab = "scenario" | "results" | "history";

export default function Workspace() {
  const { aoiId = "" } = useParams();
  const nav = useNavigate();
  const snack = useSnackbar();
  const [status, setStatus] = useState<AoiStatus | null>(null);
  const [st, setSt] = useState<StaticLayers | null>(null);
  const [fc, setFc] = useState<Forecast | null>(null);
  const [p, setP] = useState<ScenarioParams>(() => defaultParams(aoiId));
  const [run, setRun] = useState<RunResult | null>(null);
  const [prev, setPrev] = useState<RunResult | null>(null);
  const [roads, setRoads] = useState<GeoJSON.FeatureCollection | null>(null);
  const [routes, setRoutes] = useState<GeoJSON.FeatureCollection | null>(null);
  const [hist, setHist] = useState<HistoryAoi | null>(null);
  const [hour, setHour] = useState(1);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drawMode, setDrawMode] = useState<DrawMode>(null);
  const [fly, setFly] = useState<{ lon: number; lat: number; zoom?: number; t: number } | null>(null);
  const [tab, setTab] = useState<Tab>("scenario");
  const [fitT, setFitT] = useState(0);
  const [chatOpen, setChatOpen] = useState(false);
  const [mapType, setMapType] = useState<MapType>("hybrid");
  const [pending, setPending] = useState<{ lng: number; lat: number } | null>(null);
  const [cap, setCap] = useState("200");
  const [on, setOn] = useState<Set<LayerKey>>(new Set(["depth", "roads", "routes", "shelters", "assembly", "bridges", "medical", "streams", "drains"]));

  const set = useCallback((patch: Partial<ScenarioParams>) => setP((x) => ({ ...x, ...patch })), []);
  const toggle = (k: LayerKey) => setOn((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });
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

  const loadRun = useCallback(async (r: RunResult, keepPrev = true) => {
    setRun((cur) => { if (keepPrev && cur && cur.run_id !== r.run_id) setPrev(cur); return r; });
    setP({ ...defaultParams(aoiId), ...r.params });
    setHour(r.rain_series_mm_h.length);
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
    if (status?.latest_run_id) getRun(status.latest_run_id).then((r) => loadRun(r, false)).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, aoiId]);

  async function doRun() {
    setRunning(true);
    setError(null);
    try {
      const r = await createRun(p);
      await loadRun(r);
      setTab("results");
      snack(r.capacity_gap_people > 0 ? `Done: ${nf(r.people_to_evacuate)} people to move, ${nf(r.capacity_gap_people)} without a place` : `Done: ${nf(r.people_to_evacuate)} people to move, all placed`,
        { label: "Advisory", onClick: () => nav(`/area/${aoiId}/run/${r.run_id}/advisory`) });
    } catch (e) {
      setError(String((e as Error).message));
      snack("The scenario could not run: " + String((e as Error).message));
    } finally { setRunning(false); }
  }

  const layers = useMemo(() => {
    const L: Layer[] = [];
    const area = status?.bbox ? areaLayers(status.bbox) : null;
    if (area) L.push(area[0]);
    if (!st) { if (area) L.push(area[1]); return L; }
    const c = st.corners;
    for (const k of ["fsi", "lsi_static", "hand", "crowd", "streams"] as const) {
      if (on.has(k) && st.layers[k]) L.push(bitmap(`static-${k}`, st.layers[k], c, k === "streams" ? 0.9 : 0.65));
    }
    if (run) {
      const oc = run.overlay_corners.length ? run.overlay_corners : c;
      if (on.has("lsi") && run.lsi_png_url) L.push(bitmap(`lsi-${run.run_id}-${hour}`, run.lsi_png_url.replace(/lsi_h\d+/, `lsi_h${hour}`), oc, 0.55));
      if (on.has("depth")) L.push(bitmap(`depth-${run.run_id}-${hour}`, run.depth_png_urls[hour - 1], oc, 0.9));
      if (on.has("ponding") && run.ponding_png_url) L.push(bitmap(`pond-${run.run_id}`, run.ponding_png_url, oc, 0.75));
      if (on.has("drains") && run.drains?.length) L.push(...points("drains", run.drains, [161, 66, 244, 255], 6, (d) => d.id));
      if (on.has("roads") && roads) L.push(roadsLayer("roads", roads, hour));
      if (on.has("routes") && routes) L.push(routesLayer("routes", routes));
      if (on.has("bridges")) L.push(...points("bridges", run.bridges, (b) => b.first_closed_hour == null ? COLORS.open : b.first_closed_hour <= hour ? COLORS.closed : COLORS.closesLater, 6));
      if (on.has("assembly")) L.push(...points("assembly", run.assembly_points, COLORS.assembly, 7, (a) => a.id));
      if (on.has("medical")) L.push(...points("staging", run.staging_points, COLORS.staging, 7, (s) => s.id));
    }
    if (on.has("shelters")) {
      // label only shelters in use (or all when there are few), so dense cities stay readable
      const sh = run ? run.shelters.filter((s) => s.kind !== "assembly_point") : [];
      const few = (run ? sh.length : st.shelters.length) <= 40;
      if (run) {
        L.push(...points("shelters", sh, (s) => (s.status === "usable" ? COLORS.shelter : COLORS.shelterOff),
          (s) => (s.assigned > 0 ? 6 + 10 * Math.min(1, s.assigned / Math.max(1, s.capacity)) : few ? 6 : 3)));
        L.push(...points("shelters-used", sh.filter((s) => few || s.assigned > 0), COLORS.shelter, 0.1, (s) => s.id));
      } else L.push(...points("shelters", st.shelters, COLORS.shelter, few ? 8 : 3, few ? (s) => s.id : undefined));
    }
    if (on.has("medical")) L.push(...points("medical", st.medical, COLORS.medical, st.medical.length > 30 ? 4 : 7, st.medical.length > 30 ? undefined : () => "+"));
    if (on.has("streams")) L.push(...points("hotspots", st.hotspots.slice(0, 8), COLORS.hotspot, 5));
    if (on.has("crowd")) L.push(...points("crowdhs", st.crowd_hotspots, COLORS.crowd, 6, (x) => x.id));
    if (on.has("history") && hist) {
      L.push(...points("hist-glc", hist.landslides, [189, 0, 38, 255], 7, () => "landslide"));
      const web = (hist.web ?? []).filter((w) => w.marker).map((w) => ({ lon: w.marker!.lng, lat: w.marker!.lat, label: w.date.slice(0, 4) }));
      L.push(...points("hist-web", web, [251, 188, 4, 255], 6, (w) => w.label));
    }
    if (p.blocked_polygons.length) L.push(polygonsLayer("blocked", p.blocked_polygons));
    if (p.extra_shelters.length) L.push(...points("extra", p.extra_shelters.map((s) => ({ ...s, lon: s.lng })), COLORS.shelter, 9, (s) => s.name));
    if (area) {
      // border above the rasters but below roads and points: insert after the last bitmap layer
      let i = 0; L.forEach((x, k) => { if (/^(area-mask|static-|lsi-|depth-|pond-)/.test(x.id)) i = k + 1; });
      L.splice(i, 0, area[1]);
    }
    return L;
  }, [status?.bbox, st, run, roads, routes, hour, on, p.blocked_polygons, p.extra_shelters, hist]);

  const done = status?.status ? STEPS.filter(([k]) => status.status![k] === "ready").length : 0;
  const days = fc?.daily.map((d, i) => (i === 0 ? "Today" : new Date(d.date + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric" }))) ?? [];
  const onHist = useCallback((h: HistoryAoi) => { setHist(h); }, []);

  return (
    <div className="workspace">
      <aside className="ws-panel" aria-label="Scenario and results">
        <Tabs value={tab} onChange={setTab} withIcons tabs={[
          { value: "scenario", label: "Scenario", icon: "tune" },
          { value: "results", label: "Results", icon: "insights", badge: run && run.capacity_gap_people > 0 ? "!" : undefined },
          { value: "history", label: "History", icon: "history" },
        ]} />
        {running ? <Linear indeterminate /> : <div style={{ height: 4 }} />}
        <div className="panel-body">
          {!ready && <div className="stack-s"><div className="shimmer" style={{ height: 120 }} /><div className="shimmer" style={{ height: 200 }} /></div>}
          {ready && st && tab === "scenario" && (
            <ScenarioPanel p={p} set={set} replace={setP} shelters={st.shelters} drawMode={drawMode} setDrawMode={setDrawMode} days={days} />
          )}
          {ready && tab === "results" && (run ? <Results run={run} hour={hour} onFly={onFly} previous={prev} /> : (
            <div className="stack" style={{ alignItems: "center", textAlign: "center", padding: "48px 16px" }}>
              <Icon name="insights" className="xl muted" />
              <p className="title-m">No results yet</p>
              <p className="body-m muted">Set up the rain and press Run scenario. Try “Record” for the wettest day on record.</p>
              <Button variant="tonal" icon="tune" onClick={() => setTab("scenario")}>Open scenario</Button>
            </div>
          ))}
          {ready && tab === "history" && <HistoryPanel aoiId={aoiId} onFly={onFly} onData={onHist} />}
          {ready && status?.warnings?.length && tab === "scenario" ? (
            <details className="card tonal">
              <summary className="row" style={{ cursor: "pointer", listStyle: "none" }}><Icon name="info" /><span className="title-s grow">Area data notes ({status.warnings.length})</span><Icon name="expand_more" /></summary>
              <ul className="body-s" style={{ margin: "8px 0 0", paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }}>{status.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </details>
          ) : null}
          {error && ready && <div className="notice error"><Icon name="error" /><span>{error}</span></div>}
        </div>
        <div className="panel-foot">
          {tab === "results" && run ? (
            <div className="row nowrap">
              <Button variant="outlined" icon="replay" onClick={() => setTab("scenario")}>Edit scenario</Button>
              <Button className="grow" icon="assignment" onClick={() => nav(`/area/${aoiId}/run/${run.run_id}/advisory`)}>View advisory brief</Button>
            </div>
          ) : (
            <Button block size="lg" icon={running ? undefined : "play_arrow"} disabled={!ready || running} onClick={doRun}>
              {running ? <><span className="spinner small" style={{ borderTopColor: "currentColor" }} /> Running scenario, about a minute…</> : "Run scenario"}
            </Button>
          )}
        </div>
      </aside>

      <main className="ws-map">
        <MapCanvas center={{ lat: 30.28, lng: 78.98 }} zoom={12} layers={layers} mapTypeId={mapType}>
          <FlyTo target={fly} />
          <AreaOutline bbox={status?.bbox} fitKey={fitT} padding={{ top: 64, right: 200, bottom: 88, left: 32 }} />
          <Traffic on={on.has("traffic")} />
          <DrawControl mode={drawMode}
            onFinish={(poly) => { setDrawMode(null); set({ blocked_polygons: [...p.blocked_polygons, poly] }); snack("Road block added. Run the scenario to reroute."); }}
            onPoint={(lng, lat) => { setDrawMode(null); setPending({ lng, lat }); }} />
        </MapCanvas>

        <div className="top">
          <ForecastStrip fc={fc} selected={["forecast", "worst", "best"].includes(p.rain_source) ? p.forecast_day_index : null}
            onPick={(i) => { set({ forecast_day_index: i, rain_source: ["worst", "best"].includes(p.rain_source) ? p.rain_source : "forecast" }); setTab("scenario"); }} />
          {status?.bbox && (
            <button className="fc-chip sl" onClick={() => setFitT(Date.now())} title="Zoom to the simulated area">
              <span className="sq" />{status.name ?? "Simulated area"}<Icon name="center_focus_strong" className="sm" />
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

        <MapLegend on={on} hasRun={!!run} blocked={p.blocked_polygons.length > 0} />

        <div className="bottom">
          <LayerPanel on={on} toggle={toggle} hasRun={!!run} mapType={mapType} setMapType={setMapType} urban={status?.mode === "urban"} />
          {run ? <TimeSlider hours={run.rain_series_mm_h.length} hour={hour} setHour={setHour} rain={run.rain_series_mm_h} /> : <span className="spacer" />}
          <div style={{ marginRight: 56 }}><Fab icon="auto_awesome" label="Ask Pravah" variant="gemini" small onClick={() => setChatOpen(true)} /></div>
        </div>

        {!ready && (
          <div className="prepare surface-float stack" role="status">
            <div className="row nowrap"><span className="spinner" /><div className="grow"><div className="title-l">Preparing {status?.name ?? "area"}</div>
              <div className="body-s muted">About 2–3 minutes for a new area. You can leave this page open.</div></div></div>
            <Linear value={done / STEPS.length} />
            <ul className="steps">
              {STEPS.map(([k, label]) => {
                const s = status?.status?.[k];
                return <li key={k} className={s === "ready" ? "done" : s === "error" ? "err" : ""}>
                  <Icon name={s === "ready" ? "check_circle" : s === "error" ? "error" : "radio_button_unchecked"} className="sm" fill={s === "ready"} />{label}</li>;
              })}
            </ul>
            {error && <div className="notice error"><Icon name="error" />{error}</div>}
          </div>
        )}
      </main>

      <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} aoiId={aoiId} runId={run?.run_id ?? null}
        onNewRun={(id) => getRun(id).then((r) => { loadRun(r); setTab("results"); snack("Showing the scenario Gemini just ran"); })} />

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
