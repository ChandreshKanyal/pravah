import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMap } from "@vis.gl/react-google-maps";
import type { Layer } from "@deck.gl/core";
import { archiveAoi, createAoi, geocode, listAois } from "../api/client";
import DrawControl, { bboxKm, bboxOf, type DrawMode } from "../components/DrawControl";
import { Button, Chip, Dialog, Field, Icon, IconButton, useSnackbar } from "../components/m3";
import { areaLayers } from "../layers/factories";
import { AreaOutline, MapCanvas, type MapType } from "../components/MapCanvas";
import type { AoiListItem, GeocodeResult } from "../types/api";

const LIMIT_KM = 10;  // one limit for every area (backend models/aoi.py)
type BBox = [number, number, number, number];
const DEMOS: { name: string; bbox: BBox; icon: string; note: string }[] = [
  { name: "Rudraprayag", bbox: [78.93, 30.24, 79.03, 30.33], icon: "landscape", note: "Uttarakhand · river confluence, steep hills" },
  { name: "Mumbai Kurla–Mithi", bbox: [72.865, 19.06, 72.895, 19.09], icon: "location_city", note: "Maharashtra · urban waterlogging" },
];

function Fly({ to }: { to: { bbox?: BBox | null; lat?: number; lng?: number; zoom?: number } | null }) {
  const map = useMap();
  useEffect(() => {
    if (!map || !to) return;
    if (to.bbox && to.bbox[0] != null) map.fitBounds({ west: to.bbox[0], south: to.bbox[1], east: to.bbox[2], north: to.bbox[3] }, 48);
    else if (to.lat != null && to.lng != null) { map.panTo({ lat: to.lat, lng: to.lng }); map.setZoom(to.zoom ?? 12); }
  }, [map, to]);
  return null;
}

export default function Explore() {
  const nav = useNavigate();
  const snack = useSnackbar();
  const [mode, setMode] = useState<DrawMode>(null);
  const [draft, setDraft] = useState<{ bbox: BBox; name: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [fly, setFly] = useState<{ bbox?: BBox | null; lat?: number; lng?: number; zoom?: number } | null>(null);
  const [sp] = useSearchParams();
  useEffect(() => {  // ?lat=&lng=&zoom=&label= (from the assistant's "go to"): fly there and fill the search box
    const lat = Number(sp.get("lat")), lng = Number(sp.get("lng"));
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || (!lat && !lng)) return;
    setFly({ lat, lng, zoom: Number(sp.get("zoom")) || 14 });
    if (sp.get("label")) setQ(sp.get("label")!);
  }, [sp]);
  const [areas, setAreas] = useState<AoiListItem[] | null>(null);
  const [mapType, setMapType] = useState<MapType>("terrain");
  const timer = useRef<number>();
  // a prepared area opens on its brief (the bottom line first); a new one on the map
  const open = (a: AoiListItem) => nav(a.latest_run_id ? `/area/${a.aoi_id}/advisory` : `/area/${a.aoi_id}`);
  async function hide(a: AoiListItem) {
    try {
      await archiveAoi(a.aoi_id);
      setAreas((xs) => (xs ?? []).filter((x) => x.aoi_id !== a.aoi_id));
      snack(`${a.name} removed from the list`, { label: "Undo", onClick: () => archiveAoi(a.aoi_id, false).then(() => listAois().then(setAreas)) });
    } catch (e) { snack(String((e as Error).message)); }
  }

  useEffect(() => { listAois().then(setAreas).catch(() => setAreas([])); }, []);

  useEffect(() => {
    window.clearTimeout(timer.current);
    if (q.trim().length < 3) { setResults([]); return; }
    timer.current = window.setTimeout(() => geocode(q).then(setResults).catch(() => setResults([])), 350);
  }, [q]);

  const layers = useMemo(() => {
    const L: Layer[] = [];
    if (draft) { const a = areaLayers(draft.bbox); L.push(a.mask, ...a.border); }
    return L;
  }, [draft?.bbox]);

  const size = draft ? bboxKm(draft.bbox) : null;
  const tooBig = !!(draft && size && (size[0] > LIMIT_KM || size[1] > LIMIT_KM));

  async function submit() {
    if (!draft || tooBig) return;
    setBusy(true);
    try {
      const r = await createAoi(draft.bbox, draft.name.trim() || "Unnamed area");
      nav(`/area/${r.aoi.aoi_id}`);
    } catch (e) {
      snack(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  }

  // Demo cards open the prepared area directly when one exists; otherwise they pre-fill the prepare dialog.
  const ready = (areas ?? []).filter((a) => a.state === "ready" || a.state === "partial");
  const demoArea = (d: (typeof DEMOS)[number]) => ready.find((a) => a.name.toLowerCase().startsWith(d.name.split(" ")[0].toLowerCase()));
  const demoIds = new Set(DEMOS.map(demoArea).filter(Boolean).map((a) => a!.aoi_id));
  const seen = new Set<string>();
  const recent = ready.filter((a) => {
    const k = a.name.trim().toLowerCase();
    if (demoIds.has(a.aoi_id) || seen.has(k)) return false;
    seen.add(k);
    return true;
  }).slice(0, 3);
  const drawing = mode === "rectangle";
  const toggleDraw = () => setMode(drawing ? null : "rectangle");

  return (
    <div className="explore">
      <MapCanvas center={{ lat: 22.5, lng: 82 }} zoom={5} layers={layers} mapTypeId={mapType} streetView={false}>
        <Fly to={fly} />
        <AreaOutline bbox={draft?.bbox} padding={{ top: 80, right: 80, bottom: 80, left: 440 }} />
        <DrawControl mode={mode} onFinish={(p) => { setMode(null); setDraft({ bbox: bboxOf(p), name: "" }); }} />
      </MapCanvas>

      <aside className="left">
        <div className="search-wrap">
          <div className="search">
            <Icon name="search" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search a town, district or river" aria-label="Search places"
              onKeyDown={(e) => { if (e.key === "Enter" && results[0]) { setFly({ bbox: results[0].viewport, lat: results[0].lat, lng: results[0].lng }); setResults([]); } }} />
            {q && <IconButton icon="close" label="Clear" onClick={() => { setQ(""); setResults([]); }} />}
          </div>
          {results.length > 0 && (
            <div className="search-results" role="listbox">
              {results.map((r) => (
                <button key={r.label + r.lat} className="sl" role="option" onClick={() => { setFly({ bbox: r.viewport, lat: r.lat, lng: r.lng }); setResults([]); setQ(r.label); }}>
                  <Icon name="location_on" /> <span>{r.label}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="panel">
          <div className="intro">
            <h1>Plan for floods and landslides</h1>
            <p>Draw an area to see flood depth, landslide risk, who is exposed and where people can go, hour by hour.</p>
            <div className="row">
              <Button icon={drawing ? "close" : "crop_free"} onClick={toggleDraw}>{drawing ? "Cancel drawing" : "Draw an area"}</Button>
              <Button variant="text" onClick={() => nav("/methods")}>How it works</Button>
            </div>
          </div>

          <div className="group">
            <div className="group-label">Try a prepared area</div>
            {DEMOS.map((d) => {
              const a = demoArea(d);
              return (
                <button key={d.name} className="row-item sl" onClick={() => {
                  if (a) open(a);
                  else { setDraft({ bbox: d.bbox, name: d.name }); }
                }}>
                  <span className={`avatar ${d.icon === "location_city" ? "urban" : "river"}`}><Icon name={d.icon} /></span>
                  <span className="txt"><span className="t">{d.name}</span><span className="s">{d.note}</span></span>
                  <Icon name="chevron_right" className="trail" />
                </button>
              );
            })}
          </div>

          {areas === null && <div className="group"><div className="shimmer" style={{ height: 56, borderRadius: 12 }} /></div>}
          {recent.length > 0 && (
            <div className="group">
              <div className="group-label">Recent</div>
              {recent.map((a) => (
                <div key={a.aoi_id} className="row-item-wrap">
                  <button className="row-item sl" onClick={() => open(a)}>
                    <span className="avatar plain"><Icon name="history" /></span>
                    <span className="txt"><span className="t">{a.name}</span>
                      <span className="s">{bboxKm(a.bbox).map((x) => x.toFixed(0)).join(" × ")} km</span></span>
                  </button>
                  <IconButton icon="close" label={`Remove ${a.name} from the list`} small onClick={() => hide(a)} />
                </div>
              ))}
            </div>
          )}
          {(areas?.length ?? 0) > 0 && (
            <button className="row-item sl" onClick={() => nav("/projects")}>
              <span className="avatar plain"><Icon name="folder_open" /></span>
              <span className="txt"><span className="t">All projects</span><span className="s">Every area and every saved run</span></span>
            </button>
          )}
          <div className="credits">Built on Google Cloud: Gemini on Vertex AI, Earth Engine, Google Maps Platform, Firebase. Open data: Copernicus DEM, WorldPop, Open Buildings, OpenStreetMap, CHIRPS, NASA GLC.</div>
        </div>
      </aside>

      <div className="top-chips chips">
        <Chip variant="elevated" label="Satellite" icon="satellite_alt" selected={mapType === "hybrid"} onClick={() => setMapType(mapType === "hybrid" ? "terrain" : "hybrid")} />
      </div>

      {drawing && (
        <div className="draw-hint" role="status">
          <Icon name="touch_app" /> Drag on the map to draw an area, up to 15 × 15 km
          <button className="btn btn-text sl" onClick={() => setMode(null)}>Cancel</button>
        </div>
      )}

      <Dialog open={!!draft} title="Prepare this area" icon="landscape" onClose={() => setDraft(null)}
        actions={<>
          <Button variant="text" onClick={() => setDraft(null)}>Cancel</Button>
          <Button onClick={submit} disabled={busy || tooBig} icon={busy ? undefined : "arrow_forward"} iconRight>{busy ? "Starting…" : "Prepare area"}</Button>
        </>}>
        {draft && size && (
          <div className="stack">
            <p className="body-m muted">Pravah gathers terrain, rivers, land cover, population, buildings, roads and shelters for this box. A new area takes about 2–3 minutes; areas prepared before open instantly.</p>
            <Field label="Area name" support="Shown in reports, e.g. the town or ward">
              <input value={draft.name} autoFocus onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder=" " />
            </Field>
            <div className="prep-models">
              <Icon name="auto_awesome_motion" className="sm" />
              <span className="body-s">No mode to choose: every area gets <b>river flooding</b>, <b>street waterlogging</b> and <b>landslides</b>.
                Which applies where is worked out from the terrain, rivers and built-up land.</span>
            </div>
            <div className={`notice ${tooBig ? "error" : "info"}`}>
              <Icon name={tooBig ? "error" : "straighten"} />
              <span>{size[0].toFixed(1)} km × {size[1].toFixed(1)} km{tooBig ? ` — too large (max ${LIMIT_KM} × ${LIMIT_KM} km). Draw a smaller area.` : ` · within the ${LIMIT_KM} km limit`}</span>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}
