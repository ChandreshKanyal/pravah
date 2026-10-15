import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useMap } from "@vis.gl/react-google-maps";
import type { Layer } from "@deck.gl/core";
import { createRun, getAoiStatus, getForecast, getGeoJson, getStaticLayers } from "../api/client";
import DrawControl, { type DrawMode } from "../components/DrawControl";
import ForecastStrip from "../components/ForecastStrip";
import LayerPanel, { type LayerKey } from "../components/LayerPanel";
import { MapCanvas } from "../components/MapCanvas";
import Results from "../components/Results";
import ScenarioPanel from "../components/ScenarioPanel";
import TimeSlider from "../components/TimeSlider";
import { COLORS, bitmap, points, polygonsLayer, roadsLayer, routesLayer } from "../layers/factories";
import { defaultParams, type AoiStatus, type Forecast, type RunResult, type ScenarioParams, type StaticLayers } from "../types/api";

const STEPS = ["terrain", "hydro30", "landcover", "hazard_hist", "population", "buildings", "osm", "derived", "hydrology",
  "overlays", "fsi", "lsi", "building_proxy", "network"];

function FlyTo({ target }: { target: { lon: number; lat: number; zoom?: number } | null }) {
  const map = useMap();
  useEffect(() => {
    if (map && target) {
      map.panTo({ lat: target.lat, lng: target.lon });
      if (target.zoom) map.setZoom(target.zoom);
    }
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

export default function Workspace() {
  const { aoiId = "" } = useParams();
  const [status, setStatus] = useState<AoiStatus | null>(null);
  const [st, setSt] = useState<StaticLayers | null>(null);
  const [fc, setFc] = useState<Forecast | null>(null);
  const [p, setP] = useState<ScenarioParams>(() => defaultParams(aoiId));
  const [run, setRun] = useState<RunResult | null>(null);
  const [history, setHistory] = useState<RunResult[]>([]);
  const [roads, setRoads] = useState<GeoJSON.FeatureCollection | null>(null);
  const [routes, setRoutes] = useState<GeoJSON.FeatureCollection | null>(null);
  const [hour, setHour] = useState(1);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drawMode, setDrawMode] = useState<DrawMode>(null);
  const [fly, setFly] = useState<{ lon: number; lat: number; zoom?: number } | null>(null);
  const [on, setOn] = useState<Set<LayerKey>>(new Set(["depth", "roads", "routes", "shelters", "assembly", "bridges", "medical", "streams"]));

  const set = useCallback((patch: Partial<ScenarioParams>) => setP((x) => ({ ...x, ...patch })), []);
  const toggle = (k: LayerKey) => setOn((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const ready = status?.state === "ready" || status?.state === "partial";

  // poll preparation status
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const s = await getAoiStatus(aoiId);
        if (stop) return;
        setStatus(s);
        if (s.state !== "ready" && s.state !== "partial") setTimeout(tick, 3000);
      } catch (e) {
        if (!stop) setError(String((e as Error).message));
      }
    };
    tick();
    return () => { stop = true; };
  }, [aoiId]);

  useEffect(() => {
    if (!ready) return;
    getStaticLayers(aoiId).then((s) => {
      setSt(s);
      const xs = s.corners.map((c) => c[0]), ys = s.corners.map((c) => c[1]);
      setFly({ lon: (Math.min(...xs) + Math.max(...xs)) / 2, lat: (Math.min(...ys) + Math.max(...ys)) / 2, zoom: 13 });
    }).catch((e) => setError(String(e.message)));
    getForecast(aoiId, p.duration_h).then(setFc).catch(() => setFc(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, aoiId]);

  async function doRun() {
    setRunning(true);
    setError(null);
    try {
      const r = await createRun(p);
      setRun(r);
      setHistory((h) => [r, ...h].slice(0, 8));
      setHour(r.rain_series_mm_h.length);
      const [rd, rt] = await Promise.all([
        r.roads_geojson_url ? getGeoJson(r.roads_geojson_url) : Promise.resolve(null),
        r.routes_geojson_url ? getGeoJson(r.routes_geojson_url) : Promise.resolve(null),
      ]);
      setRoads(rd);
      setRoutes(rt);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setRunning(false);
    }
  }

  const layers = useMemo(() => {
    const L: Layer[] = [];
    if (!st) return L;
    const c = st.corners;
    for (const k of ["fsi", "lsi_static", "hand", "crowd", "streams"] as const) {
      if (on.has(k) && st.layers[k]) L.push(bitmap(`static-${k}`, st.layers[k], c, k === "streams" ? 0.9 : 0.65));
    }
    if (run) {
      const oc = run.overlay_corners.length ? run.overlay_corners : c;
      if (on.has("lsi") && run.lsi_png_url) L.push(bitmap(`lsi-${run.run_id}-${hour}`, run.lsi_png_url.replace(/lsi_h\d+/, `lsi_h${hour}`), oc, 0.55));
      if (on.has("depth")) L.push(bitmap(`depth-${run.run_id}-${hour}`, run.depth_png_urls[hour - 1], oc, 0.9));
      if (on.has("roads") && roads) L.push(roadsLayer("roads", roads, hour));
      if (on.has("routes") && routes) L.push(routesLayer("routes", routes));
      if (on.has("bridges")) L.push(...points("bridges", run.bridges, (b) => b.first_closed_hour == null ? COLORS.open : b.first_closed_hour <= hour ? COLORS.closed : COLORS.closesLater, 6));
      if (on.has("assembly")) L.push(...points("assembly", run.assembly_points, COLORS.assembly, 7, (a) => a.id));
      if (on.has("medical")) L.push(...points("staging", run.staging_points, COLORS.staging, 7, (s) => s.id));
    }
    if (on.has("shelters")) {
      if (run) L.push(...points("shelters", run.shelters.filter((s) => s.kind !== "assembly_point"),
        (s) => (s.status === "usable" ? COLORS.shelter : COLORS.shelterOff), (s) => 6 + 10 * Math.min(1, s.assigned / Math.max(1, s.capacity)), (s) => s.id));
      else L.push(...points("shelters", st.shelters, COLORS.shelter, 8, (s) => s.id));
    }
    if (on.has("medical")) L.push(...points("medical", st.medical, COLORS.medical, 7, (m) => "+"));
    if (on.has("streams")) L.push(...points("hotspots", st.hotspots.slice(0, 8), COLORS.hotspot, 5));
    if (on.has("crowd")) L.push(...points("crowdhs", st.crowd_hotspots, COLORS.crowd, 6, (x) => x.id));
    if (p.blocked_polygons.length) L.push(polygonsLayer("blocked", p.blocked_polygons));
    if (p.extra_shelters.length) L.push(...points("extra", p.extra_shelters.map((s) => ({ ...s, lon: s.lng })), COLORS.shelter, 9, (s) => s.name));
    return L;
  }, [st, run, roads, routes, hour, on, p.blocked_polygons, p.extra_shelters]);

  const doneSteps = status?.status ? STEPS.filter((k) => status.status![k] === "ready").length : 0;
  const days = fc?.daily.map((d) => new Date(d.date + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })) ?? [];

  return (
    <div className="workspace">
      <header className="ws-top">
        <ForecastStrip fc={fc} selected={p.forecast_day_index} onPick={(i) => set({ forecast_day_index: i, rain_source: ["worst", "best"].includes(p.rain_source) ? p.rain_source : "forecast" })} />
      </header>
      {!ready && (
        <div className="preparing card">
          <h3>Preparing area…</h3>
          <progress max={STEPS.length} value={doneSteps} /> <span>{doneSteps}/{STEPS.length} layer groups</span>
          <p className="muted tiny">Terrain, rivers, land cover, population, buildings, roads, susceptibility and shelters. About 2–3 minutes for a new area.</p>
          {error && <p className="error">{error}</p>}
        </div>
      )}
      <LayerPanel on={on} toggle={toggle} hasRun={!!run} />
      <main className="ws-map">
        <MapCanvas center={{ lat: 30.28, lng: 78.98 }} zoom={12} layers={layers}>
          <FlyTo target={fly} />
          <Traffic on={on.has("traffic")} />
          <DrawControl mode={drawMode}
            onFinish={(poly) => { setDrawMode(null); set({ blocked_polygons: [...p.blocked_polygons, poly] }); }}
            onPoint={(lng, lat) => {
              setDrawMode(null);
              const cap = Number(window.prompt("Shelter capacity (people)?", "200") || 0);
              if (cap > 0) set({ extra_shelters: [...p.extra_shelters, { id: `U${p.extra_shelters.length + 1}`, name: `User shelter ${p.extra_shelters.length + 1}`, lat, lng, capacity: cap }] });
            }} />
        </MapCanvas>
        {run && <TimeSlider hours={run.rain_series_mm_h.length} hour={hour} setHour={setHour} rain={run.rain_series_mm_h} />}
      </main>
      <aside className="ws-right">
        {ready && st && (
          <ScenarioPanel p={p} set={set} shelters={st.shelters} onRun={doRun} running={running} drawMode={drawMode} setDrawMode={setDrawMode} days={days} />
        )}
        {error && ready && <p className="error card">{error}</p>}
        {history.length > 1 && run && (
          <div className="card compare tiny">
            <b>Compared with previous run:</b> capacity gap {history[1].capacity_gap_people.toLocaleString("en-IN")} → {run.capacity_gap_people.toLocaleString("en-IN")},
            {" "}people in flood water {Math.max(0, ...history[1].exposure.exposed_pop_by_hour)} → {Math.max(0, ...run.exposure.exposed_pop_by_hour)}
          </div>
        )}
        {run ? <Results run={run} hour={hour} onFly={(lon, lat) => setFly({ lon, lat, zoom: 15 })} /> :
          ready && <div className="card muted">Set a scenario and press <b>Run scenario</b>. Try "Historic max" for a heavy-rain test.</div>}
        {status?.warnings?.length ? (
          <details className="card warnings"><summary>Area data notes ({status.warnings.length})</summary>
            <ul>{status.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>
        ) : null}
      </aside>
    </div>
  );
}
