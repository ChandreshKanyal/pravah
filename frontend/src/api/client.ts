import type {
  AOI, AoiListItem, AoiStatus, Advisory, ChatResponse, Forecast, GeocodeResult, HistoryAoi, HistoryIndia, PhotoDoc, PlanResponse,
  RunResult, ScenarioParams, StaticLayers, VerificationItem,
} from "../types/api";

export const BASE = import.meta.env.VITE_API_BASE ?? "/api";

/** Backend paths come back as "/api/..."; resolve them against the configured base. */
export const apiUrl = (path: string) => (path.startsWith("/api") ? BASE + path.slice(4) : path);

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(apiUrl(path), { headers: { "content-type": "application/json" }, ...init });
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return r.json();
}

export type Health = { ok: boolean; ee: boolean; vertex: boolean; firestore: boolean };

export const getHealth = () => call<Health>("/api/health");
export const createAoi = (bbox: AOI["bbox"], name: string, mode: AOI["mode"]) =>
  call<{ aoi: AOI; state: string }>("/api/aoi", { method: "POST", body: JSON.stringify({ bbox, name, mode }) });
export const getAoiStatus = (id: string) => call<AoiStatus>(`/api/aoi/${id}/status`);
export const getStaticLayers = (id: string) => call<StaticLayers>(`/api/aoi/${id}/static-layers`);
export const getForecast = (id: string, duration_h: number) => call<Forecast>(`/api/forecast?aoi_id=${id}&duration_h=${duration_h}`);
export const createRun = (p: ScenarioParams) => call<RunResult>("/api/runs", { method: "POST", body: JSON.stringify(p) });
export const getRun = (id: string) => call<RunResult>(`/api/runs/${id}`);
export const getGeoJson = (url: string) => call<GeoJSON.FeatureCollection>(url);
export const listAois = () => call<AoiListItem[]>("/api/aois");
export const geocode = (q: string) => call<GeocodeResult[]>(`/api/geocode?q=${encodeURIComponent(q)}`);
export const requestAdvisory = (runId: string, refresh = false) =>
  call<Advisory | { status: "pending"; run_id: string }>(`/api/runs/${runId}/advisory${refresh ? "?refresh=true" : ""}`, { method: "POST" });
export const getAdvisory = (runId: string) => call<Advisory>(`/api/runs/${runId}/advisory`);
export const plan = (aoi_id: string, text: string, current_params: ScenarioParams) =>
  call<PlanResponse>("/api/plan", { method: "POST", body: JSON.stringify({ aoi_id, text, current_params }) });
export const chat = (session_id: string, aoi_id: string, run_id: string | null, message: string) =>
  call<ChatResponse>("/api/chat", { method: "POST", body: JSON.stringify({ session_id, aoi_id, run_id, message }) });
export const historyIndia = () => call<HistoryIndia>("/api/history/india");
export const historyAoi = (id: string, web = false) => call<HistoryAoi>(`/api/history/aoi/${id}${web ? "?web=true" : ""}`);
export const listPhotos = (aoi_id: string) => call<PhotoDoc[]>(`/api/photos?aoi_id=${aoi_id}`);
export const verificationQueue = (aoi_id: string) => call<{ run_id: string | null; queue: VerificationItem[] }>(`/api/aoi/${aoi_id}/verification-queue`);
export async function uploadPhoto(aoi_id: string, kind: "building" | "drain", file: File, pin?: { lat: number; lng: number }): Promise<PhotoDoc> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("aoi_id", aoi_id);
  fd.append("kind", kind);
  if (pin) { fd.append("lat", String(pin.lat)); fd.append("lng", String(pin.lng)); }
  const r = await fetch(apiUrl("/api/photos"), { method: "POST", body: fd });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : `${r.status}`);
  return j;
}
export const photoUrl = (aoi_id: string, photo_id: string) => apiUrl(`/api/photos/${photo_id}.jpg?aoi_id=${aoi_id}`);
