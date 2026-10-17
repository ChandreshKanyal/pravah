import type {
  AOI, AoiListItem, AoiStatus, AreaDrain, DrainLookup, Advisory, AdvisoryVersion, ChatResponse, Forecast, GeocodeResult, HistoryAoi, HistoryIndia, Official,
  AlertDraft, Drill, Improvements, DrillEval, DrillReport, DrillSummary, EmulatorStats, EmulatorStatus, PhotoDoc, PlanResponse, ProjectArea, Review, Triggers, RunResult, RunSummary, ScenarioParams, StaticLayers, Translation, VerificationItem,
} from "../types/api";
import { idToken } from "../auth";

export const BASE = import.meta.env.VITE_API_BASE ?? "/api";

/** Backend paths come back as "/api/..."; resolve them against the configured base. */
export const apiUrl = (path: string) => (path.startsWith("/api") ? BASE + path.slice(4) : path);

async function authHeaders(): Promise<Record<string, string>> {
  const t = await idToken();
  return t ? { authorization: `Bearer ${t}` } : {};
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(apiUrl(path), { ...init, headers: { "content-type": "application/json", ...(await authHeaders()), ...(init?.headers ?? {}) } });
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
export const createAoi = (bbox: AOI["bbox"], name: string) =>
  call<{ aoi: AOI; state: string }>("/api/aoi", { method: "POST", body: JSON.stringify({ bbox, name }) });
export const getAoiStatus = (id: string) => call<AoiStatus>(`/api/aoi/${id}/status`);
export const lookupDrain = (id: string) => call<DrainLookup>(`/api/aoi/${id}/drain/lookup`, { method: "POST" });
export const setDrain = (id: string, body: { mm_h: number | null; city?: string; basis?: string; sources?: { uri: string; title?: string }[] }) =>
  call<{ drain: AreaDrain | null }>(`/api/aoi/${id}/drain`, { method: "POST", body: JSON.stringify(body) });
export const getStaticLayers = (id: string) => call<StaticLayers>(`/api/aoi/${id}/static-layers`);
export const getImprovements = (id: string) => call<Improvements>(`/api/aoi/${id}/improvements`);
export const refreshImprovements = (id: string) => call<{ state: string }>(`/api/aoi/${id}/improvements`, { method: "POST" });
export const getForecast = (id: string, duration_h: number) => call<Forecast>(`/api/forecast?aoi_id=${id}&duration_h=${duration_h}`);
type RunJob = { job_id?: string; status: "running" | "done" | "error"; run_id?: string; code?: number; error?: string };
// a run with the flow model takes minutes; holding one request open that long can be dropped on the way (the run
// finishes, the reply never arrives), so the backend answers at once and the page asks every few seconds
export async function createRun(p: ScenarioParams, opts?: { flow?: boolean }): Promise<RunResult> {
  const job = await call<RunJob>(`/api/run-jobs${opts?.flow === false ? "?flow=false" : ""}`, { method: "POST", body: JSON.stringify(p) });
  const until = Date.now() + 17 * 60_000;  // the backend reports a lost job after 16 min; this is only a backstop
  let misses = 0;
  while (Date.now() < until) {
    await new Promise((res) => setTimeout(res, 3000));
    let s: RunJob;
    try { s = await call<RunJob>(`/api/run-jobs/${job.job_id}`); misses = 0; } catch (e) {
      if (++misses >= 10) throw e;  // a few failed polls (network blip) are retried; the run keeps going on the server
      continue;
    }
    if (s.status === "done" && s.run_id) return getRun(s.run_id);
    if (s.status === "error") throw new Error(s.error || `${s.code ?? "error"}`);
  }
  throw new Error("The run took too long; open it from the runs list when it finishes.");
}
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
  const r = await fetch(apiUrl("/api/photos"), { method: "POST", body: fd, headers: await authHeaders() });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : `${r.status}`);
  return j;
}
export const photoUrl = (aoi_id: string, photo_id: string) => apiUrl(`/api/photos/${photo_id}.jpg?aoi_id=${aoi_id}`);
export const archiveAoi = (id: string, archived = true) =>
  call<{ archived: boolean }>(`/api/aoi/${id}/archive`, { method: "POST", body: JSON.stringify({ archived }) });
export const getAoiRuns = (id: string, limit = 10, archived = false) =>
  call<RunSummary[]>(`/api/aoi/${id}/runs?limit=${limit}${archived ? "&archived=true" : ""}`);
export const getProjects = () => call<ProjectArea[]>("/api/projects");
export type AssistantAction = { kind: "go_to_place" | "open_area" | "prepare_area" | "run_scenario" | "set_layers" | "open_page"; label: string; args: Record<string, any> };
export type AssistantReply = { reply: string; proposals: AssistantAction[]; sources: { title: string; uri: string }[]; search_entry_point: string; tools_called: string[] };
export const askAssistant = (body: { session_id: string; message: string; page: string; aoi_id?: string | null; run_id?: string | null }) =>
  call<AssistantReply>("/api/assistant", { method: "POST", body: JSON.stringify(body) });
export type AssistantEvent =
  | { type: "step"; label: string } | { type: "thought"; text: string } | { type: "delta"; text: string }
  | ({ type: "final" } & AssistantReply) | { type: "error"; message: string };
/** Streams the assistant's steps, thinking and answer text (server-sent events over a POST). */
export async function askAssistantStream(body: { session_id: string; message: string; page: string; aoi_id?: string | null; run_id?: string | null },
  onEvent: (e: AssistantEvent) => void): Promise<void> {
  const r = await fetch(apiUrl("/api/assistant/stream"), { method: "POST", headers: { "content-type": "application/json", ...(await authHeaders()) }, body: JSON.stringify(body) });
  if (!r.ok || !r.body) throw new Error(String(r.status));
  const reader = r.body.getReader(), dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      for (const line of chunk.split("\n")) if (line.startsWith("data: ")) { try { onEvent(JSON.parse(line.slice(6))); } catch { /* partial */ } }
    }
  }
}
export const deleteRun = (runId: string) => call<{ run_id: string; aoi_id?: string }>(`/api/runs/${runId}`, { method: "DELETE" });
export const deleteAoi = (aoiId: string) => call<{ aoi_id: string; runs: number }>(`/api/aoi/${aoiId}`, { method: "DELETE" });
export const setRunMeta = (runId: string, meta: { title?: string; notes?: string; starred?: boolean; archived?: boolean; make_current?: boolean }) =>
  call<{ run_id: string }>(`/api/runs/${runId}/meta`, { method: "PATCH", body: JSON.stringify(meta) });
export const setOfficial = (id: string, o: Partial<Official>) => call<Official>(`/api/aoi/${id}/official`, { method: "PUT", body: JSON.stringify(o) });
export const reviewAdvisory = (runId: string, body: { state: Review["state"]; name?: string; designation?: string; note?: string; version?: number }) =>
  call<Advisory>(`/api/runs/${runId}/advisory/review`, { method: "POST", body: JSON.stringify(body) });
export const advisoryVersions = (runId: string) => call<AdvisoryVersion[]>(`/api/runs/${runId}/advisory/versions`);
export const advisoryVersion = (runId: string, v: number) => call<Advisory>(`/api/runs/${runId}/advisory/versions/${v}`);
export const translateAdvisory = (runId: string, lang = "hi") => call<Translation>(`/api/runs/${runId}/advisory/translate?lang=${lang}`, { method: "POST" });
export const shareTextUrl = (runId: string, lang = "en") => apiUrl(`/api/runs/${runId}/advisory/share.txt?lang=${lang}`);
export async function shareText(runId: string, lang = "en"): Promise<string> {
  const r = await fetch(shareTextUrl(runId, lang));
  if (!r.ok) throw new Error(`${r.status}`);
  return r.text();
}
export const runAudit = (runId: string) => call<{ at: string; action: string; by: string; verified: boolean; version?: number; note?: string }[]>(`/api/runs/${runId}/audit`);

// AI emulator of the 2D flow model (per area) and the rain triggers derived from it
export type WhatIf = { total_mm: number; hours: number; shape: "constant" | "triangular_front"; river_offset_m: number };
const wq = (q: WhatIf) => `total_mm=${q.total_mm}&hours=${q.hours}&shape=${q.shape}&river_offset_m=${q.river_offset_m}`;
export const getEmulator = (aoi: string) => call<EmulatorStatus>(`/api/aoi/${aoi}/emulator`);
export const trainEmulator = (aoi: string, force = false) => call<{ state: string }>(`/api/aoi/${aoi}/emulator${force ? "?force=true" : ""}`, { method: "POST" });
export const predictEmulator = (aoi: string, q: WhatIf) => call<EmulatorStats>(`/api/aoi/${aoi}/emulator/predict?${wq(q)}`);
export const emulatorPng = (aoi: string, q: WhatIf) => `/api/aoi/${aoi}/emulator/predict.png?${wq(q)}`;
export const getTriggers = (aoi: string) => call<Triggers>(`/api/aoi/${aoi}/triggers`);

// Tabletop drills (Gemini exercise controller) on a stored run
export const startDrill = (runId: string, participant: string) => call<Drill>(`/api/runs/${runId}/drill`, { method: "POST", body: JSON.stringify({ participant }) });
export const listDrills = (runId: string) => call<DrillSummary[]>(`/api/runs/${runId}/drills`);
export const getDrill = (id: string) => call<Drill>(`/api/drills/${id}`);
export const answerDrill = (id: string, index: number, response: string) => call<DrillEval>(`/api/drills/${id}/answer`, { method: "POST", body: JSON.stringify({ index, response }) });
export const drillReport = (id: string) => call<DrillReport>(`/api/drills/${id}/report`, { method: "POST" });

// Public alert drafts (CAP 1.2, status Draft) for SACHET
export const getAlert = (runId: string) => call<AlertDraft>(`/api/runs/${runId}/alert`);
export const draftAlert = (runId: string) => call<AlertDraft>(`/api/runs/${runId}/alert`, { method: "POST" });
export const capUrl = (runId: string) => apiUrl(`/api/runs/${runId}/alert/cap.xml`);

export type RainHours = { series: number[]; label: string; start_local: string | null; warnings: string[];
  base_mean_mm_h?: number; base_peak_mm_h?: number; scaled?: string | null };  // base = the source's own rain (strength x1)
export type RainRecords = { years: number[]; annual: { year: number; mm: number; date: string | null }[]; record: { mm: number; date: string | null };
  levels: { T: 2 | 10 | 25 | 100; mm: number }[]; source: string; method: string };
/** Wettest days on record near the area and the 2/10/25/100-year daily rain (CHIRPS 2001-2024, Gumbel fit). */
export const rainRecords = (aoi: string) => call<RainRecords>(`/api/aoi/${aoi}/rain-records`);
/** The exact hourly rain a scenario would use (the run's own rain builder), for the hour-by-hour editor. */
export const rainHours = (aoi: string, p: ScenarioParams) =>
  call<RainHours>(`/api/aoi/${aoi}/rain-hours`, { method: "POST", body: JSON.stringify({ ...p, rain_series_override: null }) });
