import type { AOI, AoiStatus, Forecast, RunResult, ScenarioParams, StaticLayers } from "../types/api";

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
