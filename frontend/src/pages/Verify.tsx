import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useMap } from "@vis.gl/react-google-maps";
import { getStaticLayers, listPhotos, photoUrl, uploadPhoto, verificationQueue } from "../api/client";
import { Button, Icon, Segmented, nf, useSnackbar } from "../components/m3";
import { MapCanvas } from "../components/MapCanvas";
import { points } from "../layers/factories";
import type { PhotoDoc, VerificationItem } from "../types/api";
import { enqueue, list as listQueued, remove as unqueue, shrink, type Queued } from "../offlineQueue";

const pretty = (s?: string) => (s ?? "").replace(/^verified_/, "verified ").replace(/_/g, " ");

function MapClick({ on, onPick }: { on: boolean; onPick: (lng: number, lat: number) => void }) {
  const map = useMap();
  useEffect(() => {
    if (!map || !on) return;
    map.setOptions({ draggableCursor: "crosshair" });
    const l = map.addListener("click", (e: google.maps.MapMouseEvent) => e.latLng && onPick(e.latLng.lng(), e.latLng.lat()));
    return () => { l.remove(); map.setOptions({ draggableCursor: null }); };
  }, [map, on, onPick]);
  return null;
}

function Fly({ to }: { to: { lon: number; lat: number; z: number; t: number } | null }) {
  const map = useMap();
  useEffect(() => { if (map && to) { map.panTo({ lat: to.lat, lng: to.lon }); map.setZoom(to.z); } }, [map, to]);
  return null;
}

export default function Verify() {
  const { aoiId = "" } = useParams();
  const snack = useSnackbar();
  const [queue, setQueue] = useState<VerificationItem[] | null>(null);
  const [photos, setPhotos] = useState<PhotoDoc[]>([]);
  const [kind, setKind] = useState<"building" | "drain">("building");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [pin, setPin] = useState<{ lng: number; lat: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [last, setLast] = useState<PhotoDoc | null>(null);
  const [fly, setFly] = useState<{ lon: number; lat: number; z: number; t: number } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const [waiting, setWaiting] = useState<Queued[]>([]);
  const [online, setOnline] = useState(navigator.onLine);
  const [locating, setLocating] = useState(false);

  async function flush() {
    const qs = await listQueued(aoiId);
    setWaiting(qs);
    if (!navigator.onLine) return;
    for (const q of qs) {
      try {
        const d = await uploadPhoto(aoiId, q.kind, new File([q.blob], q.name, { type: q.blob.type || "image/jpeg" }), q.pin ?? undefined);
        await unqueue(q.id);
        setPhotos((x) => [d, ...x]);
      } catch (e) {
        if (e instanceof TypeError) break;  // still offline
        await unqueue(q.id);  // rejected by the server (e.g. no location): drop it and say why
        snack(`A saved photo could not be used: ${(e as Error).message}`);
      }
    }
    const left = await listQueued(aoiId);
    if (left.length < qs.length) snack(`${qs.length - left.length} saved photo(s) uploaded`);
    setWaiting(left);
  }
  useEffect(() => {
    flush();
    const on = () => { setOnline(true); flush(); }, off = () => setOnline(false);
    window.addEventListener("online", on); window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, [aoiId]);  // eslint-disable-line react-hooks/exhaustive-deps

  function myLocation() {
    if (!navigator.geolocation) { snack("This device cannot share its location"); return; }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => { setPin({ lng: pos.coords.longitude, lat: pos.coords.latitude }); setFly({ lon: pos.coords.longitude, lat: pos.coords.latitude, z: 18, t: Date.now() }); setLocating(false); },
      () => { snack("Location not available: drop a pin on the map instead"); setLocating(false); },
      { enableHighAccuracy: true, timeout: 15000 });
  }

  useEffect(() => {
    verificationQueue(aoiId).then((q) => setQueue(q.queue)).catch(() => setQueue([]));
    listPhotos(aoiId).then(setPhotos).catch(() => undefined);
    getStaticLayers(aoiId).then((s) => {
      const xs = s.corners.map((c) => c[0]), ys = s.corners.map((c) => c[1]);
      setFly({ lon: (Math.min(...xs) + Math.max(...xs)) / 2, lat: (Math.min(...ys) + Math.max(...ys)) / 2, z: 14, t: Date.now() });
    }).catch(() => undefined);
  }, [aoiId]);

  function pick(f: File | null | undefined) {
    if (!f) return;
    setFile(f); setLast(null);
    setPreview(URL.createObjectURL(f));
  }

  async function send() {
    if (!file) return;
    setBusy(true);
    const blob = pin ? await shrink(file).catch(() => file) : file;  // keep EXIF GPS when there is no pin
    const save = async () => {
      await enqueue({ id: crypto.randomUUID(), aoiId, kind, blob, name: file.name || "photo.jpg", pin, at: new Date().toISOString() });
      setWaiting(await listQueued(aoiId));
      snack("No connection: the photo is saved on this device and uploads when you are back online");
      setFile(null); setPreview(null); setPin(null);
    };
    if (!navigator.onLine) { await save(); setBusy(false); return; }
    try {
      const d = await uploadPhoto(aoiId, kind, new File([blob], file.name || "photo.jpg", { type: blob.type || "image/jpeg" }), pin ?? undefined);
      setLast(d);
      setPhotos((x) => [d, ...x]);
      snack(d.accepted ? "Classified and applied on the next run" : "Saved, not applied");
      setFile(null); setPreview(null); setPin(null);
    } catch (e) {
      if (e instanceof TypeError) { await save(); return; }  // network failure: keep it for later
      const m = String((e as Error).message);
      snack(m.includes("GPS") ? "No GPS in the photo: tap “Use my location” or drop a pin on the map, then send again" : m);
    } finally { setBusy(false); }
  }

  const layers = useMemo(() => [
    ...points("queue", (queue ?? []).slice(0, 50), [242, 153, 0, 255], 6),
    ...points("photos", photos, (p) => (p.accepted ? [52, 168, 83, 255] : [128, 134, 139, 255]), 7, () => ""),
    ...(pin ? points("pin", [{ lon: pin.lng, lat: pin.lat }], [11, 87, 208, 255], 10, () => "photo location") : []),
  ], [queue, photos, pin]);

  return (
    <div className="doc-page">
      <div className="doc" style={{ maxWidth: 1240 }}>
        <div className="doc-head"><div className="grow stack-s">
          <span className="label-l muted">Field check</span>
          <h1>Check buildings and drains with your own photos</h1>
          <p className="body-m muted">Upload field or drone photos taken by your teams. Gemini classifies the structure or drain; a confident result replaces the proxy class from the next run. Only your photos are used, never Google Maps imagery.</p>
        </div></div>

        {(!online || waiting.length > 0) && (
          <div className={`notice ${online ? "info" : "warn"}`}>
            <Icon name={online ? "cloud_upload" : "cloud_off"} />
            <span className="grow">{online ? `${waiting.length} photo(s) saved on this device are waiting to upload.` : `You are offline. Photos are saved on this device${waiting.length ? ` (${waiting.length} waiting)` : ""} and upload automatically when the signal returns.`}</span>
            {online && waiting.length > 0 && <Button variant="text" size="small" onClick={flush}>Upload now</Button>}
          </div>
        )}
        <div className="grid-2 verify-grid" style={{ alignItems: "start" }}>
          <div className="stack">
            <div className="card elevated stack">
              <Segmented label="Photo of" block value={kind} onChange={setKind}
                options={[{ value: "building", label: "Building", icon: "home" }, { value: "drain", label: "Drain or culvert", icon: "water_pump" }]} />
              <div className={`dropzone ${over ? "over" : ""}`} onClick={() => input.current?.click()} role="button" tabIndex={0}
                onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
                onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files?.[0]); }}>
                {preview ? <img src={preview} alt="Selected" style={{ maxHeight: 220, borderRadius: 12 }} /> : <>
                  <Icon name="add_a_photo" />
                  <span className="title-m">Take a photo or choose one</span>
                  <span className="body-s muted">JPEG or PNG up to 12 MB. Location is read from the photo's GPS; otherwise click the map.</span>
                </>}
                <input ref={input} type="file" accept="image/*" capture="environment" hidden onChange={(e) => pick(e.target.files?.[0])} />
              </div>
              <div className="row">
                <Button variant="outlined" size="small" icon="my_location" onClick={myLocation} disabled={locating}>{locating ? "Locating…" : "Use my location"}</Button>
                <span className="body-s muted grow">{pin ? `Location: ${pin.lat.toFixed(5)}, ${pin.lng.toFixed(5)}` : "No location yet (photo GPS is used if present)"}</span>
              </div>
              <div className="row nowrap verify-actions">
                {file && <Button variant="text" onClick={() => { setFile(null); setPreview(null); }}>Clear</Button>}
                <Button icon={busy ? undefined : online ? "auto_awesome" : "save"} disabled={!file || busy} onClick={send}>{busy ? "Sending…" : online ? "Classify with Gemini" : "Save for upload"}</Button>
              </div>
            </div>

            {last && (
              <div className={`notice ${last.accepted ? "ok" : "warn"}`}>
                <Icon name={last.accepted ? "verified" : "help"} />
                <div className="stack-s"><b>{last.message}</b>
                  <span className="body-s">{last.kind === "building"
                    ? `${pretty(last.result.structure_class)} · walls ${pretty(last.result.wall_material)} · roof ${pretty(last.result.roof_material)} · confidence ${Number(last.result.confidence).toFixed(2)}`
                    : `${pretty(last.result.condition)} · ${(last.result.blockage_types ?? []).join(", ") || "no blockage"} · confidence ${Number(last.result.confidence).toFixed(2)}`}</span>
                  <span className="body-s">{last.result.rationale}</span></div>
              </div>
            )}

            <div className="stack-s">
              <div className="section-title"><Icon name="photo_library" /> Photos for this area ({photos.length})</div>
              {photos.map((p) => (
                <div key={p.photo_id} className="photo-card">
                  <img src={photoUrl(aoiId, p.photo_id)} alt={`${p.kind} photo`} loading="lazy" />
                  <div className="stack-s">
                    <div className="row nowrap"><span className={`tag ${p.accepted ? "ok" : ""}`}>{p.accepted ? "applied on next run" : "not applied"}</span>
                      <span className="spacer" /><button className="icon-btn small sl" aria-label="Show on map" onClick={() => setFly({ lon: p.lon, lat: p.lat, z: 18, t: Date.now() })}><Icon name="my_location" /></button></div>
                    <span className="title-s">{p.kind === "building" ? pretty(p.override_class || p.result.structure_class) : pretty(p.result.condition)}</span>
                    <span className="body-s muted">{p.message}</span>
                  </div>
                </div>
              ))}
              {!photos.length && <p className="body-m muted">No photos yet.</p>}
            </div>
          </div>

          <div className="stack" style={{ position: "sticky", top: 16 }}>
            <div className="mini-map card elevated" style={{ padding: 0, height: 420 }}>
              <MapCanvas center={{ lat: 30.28, lng: 78.98 }} zoom={14} layers={layers} mapTypeId="hybrid" streetView={false}>
                <MapClick on={!!file} onPick={(lng, lat) => setPin({ lng, lat })} />
                <Fly to={fly} />
              </MapCanvas>
            </div>
            <div className="card outlined" style={{ padding: 0 }}>
              <div className="section-title" style={{ padding: "16px 16px 8px" }}><Icon name="checklist" /> Go and check these first</div>
              <p className="body-s muted" style={{ padding: "0 16px 8px" }}>Ranked by estimated risk × uncertainty of the proxy class × people, from the latest run.</p>
              <div className="list" style={{ maxHeight: 360, overflowY: "auto" }}>
                {queue === null && <div className="shimmer" style={{ height: 120, margin: 16 }} />}
                {queue?.slice(0, 25).map((q, i) => (
                  <div key={q.bid} className="li dense clickable sl" onClick={() => setFly({ lon: q.lon, lat: q.lat, z: 19, t: Date.now() })}>
                    <span className="label-l muted" style={{ width: 24 }}>{i + 1}</span>
                    <span className="txt"><span className="t" style={{ fontSize: 14 }}>{pretty(q.current_class)}</span><span className="s" style={{ display: "block" }}>building {q.bid} · ~{nf(q.people)} people</span></span>
                    <Icon name="chevron_right" />
                  </div>
                ))}
                {queue?.length === 0 && <p className="body-m muted" style={{ padding: 16 }}>Run a scenario to rank buildings.</p>}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
