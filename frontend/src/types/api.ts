// Mirrors backend pydantic models (backend/app/models). Keep in sync.
export type LonLat = [number, number];
export type RainSource = "forecast" | "worst" | "best" | "historical_extreme" | "manual";

export interface AOI {
  aoi_id: string;
  name: string;
  bbox: [number, number, number, number];
  mode: "river" | "urban";
  created_at: string;
}

export interface AoiStatus {
  aoi_id: string;
  state: "queued" | "preparing" | "ready" | "partial" | null;
  status: Record<string, string> | null;
  warnings: string[] | null;
  meta: Record<string, any> | null;
  prepare_seconds?: number | null;
  name?: string; bbox?: [number, number, number, number]; mode?: "river" | "urban"; latest_run_id?: string | null;
  official?: Official | null; archived?: boolean;
}

export interface Official {
  imd_warning: "green" | "yellow" | "orange" | "red" | null; imd_valid_for: string;
  cwc_station: string; cwc_level_m: number | null; cwc_warning_m: number | null; cwc_danger_m: number | null; cwc_hfl_m: number | null;
  note: string; entered_by?: string; verified?: boolean; at?: string;
}

export interface RunSummary {
  run_id: string; created_at: string; rain_label: string; people_to_evacuate: number; capacity_gap_people: number;
  demand_range: number[]; gap_range: number[]; evac_window_h: number | null; start_local: string | null;
  bridges_closing: number; bridges_total: number; flooded_km2: number; flood_peak: number; shelters_used: number;
  changes: Record<string, unknown>;
}

export interface AoiListItem { aoi_id: string; name: string; bbox: [number, number, number, number]; mode: string; state: string; latest_run_id: string | null }
export interface GeocodeResult { label: string; lat: number; lng: number; viewport: [number, number, number, number] | null }

export interface Shelter {
  id: string; name: string; kind: string; lon: number; lat: number;
  area_m2?: number; floors?: number; capacity_confidence?: string; note?: string;
  hand_m?: number; lsi_class?: number; primary?: boolean;
}

export interface Hotspot { id: string; lon: number; lat: number; upa_km2: number; type: string; depth_m?: number | null; stage_m?: number | null; in_river_channel?: boolean }
export interface CrowdHotspot { id: string; lon: number; lat: number; score: number; top_attractors: string[] }

export interface StaticLayers {
  aoi_id: string;
  layers: Record<string, string>;
  corners: LonLat[];
  hotspots: Hotspot[];
  shelters: Shelter[];
  medical: Shelter[];
  crowd_hotspots: CrowdHotspot[];
}

export interface ScenarioParams {
  aoi_id: string;
  rain_source: RainSource;
  forecast_day_index: number | null;
  manual_intensity_mm_h: number;
  duration_h: number;
  hyetograph: "constant" | "triangular_front";
  worst_multiplier: number;
  best_multiplier: number;
  river_offset_m: number;
  upstream_inflow_m3s: number;
  manning_n: number;
  pop_multiplier: number;
  pop_total_override: number | null;
  disabled_shelter_ids: string[];
  extra_shelters: { id: string; name: string; lat: number; lng: number; capacity: number }[];
  blocked_polygons: GeoJSON.Polygon[];
  travel_mode: "walk" | "drive";
  evac_start_hour: number;
  vehicle_depth_limit_m: number;
  walk_depth_limit_m: number;
  bridge_cut_stage_m: number;
  max_travel_min: number;
  sqm_per_person: number;
  preset_label?: string | null;
  visitors?: number;
}

export const defaultParams = (aoi_id: string): ScenarioParams => ({
  aoi_id, rain_source: "historical_extreme", forecast_day_index: null, manual_intensity_mm_h: 50, duration_h: 4,
  hyetograph: "constant", worst_multiplier: 1.5, best_multiplier: 0.5, river_offset_m: 0, upstream_inflow_m3s: 0, manning_n: 0.04,
  pop_multiplier: 1, pop_total_override: null, disabled_shelter_ids: [], extra_shelters: [], blocked_polygons: [],
  travel_mode: "walk", evac_start_hour: 1, vehicle_depth_limit_m: 0.3, walk_depth_limit_m: 0.5,
  bridge_cut_stage_m: 3, max_travel_min: 60, sqm_per_person: 3.5, preset_label: null, visitors: 0,
});

export interface ExposureSummary {
  total_pop: number;
  exposed_pop_by_hour: number[];
  exposed_by_depth_band: Record<string, number>;
  landslide_exposed_pop_by_hour: number[];
  buildings_by_risk: Record<string, number>;
  clusters: { id: string; centroid: LonLat; people: number; max_depth: number; risk: number; risk_class: string; dominant_class: string; place?: string; place_hi?: string }[];
}

export interface TriageRow { structure_class: string; risk_class: string; buildings: number; people: number }
export interface ShelterResult { id: string; name: string; kind: string; lon: number; lat: number; capacity: number; assigned: number; spare: number; status: string; note: string; capacity_confidence: string; place?: string }
export interface BridgeStatus { id: string; name: string; lon: number; lat: number; first_closed_hour: number | null; reason: string | null; place?: string }
export interface RouteSummary {
  from_node: number; from_lon?: number; from_lat?: number; to_shelter: string; people: number; eta_min: number;
  access_min?: number; length_km?: number; passable_until_h: number | null; use_now_gone_soon: boolean; place?: string;
}

export interface RunResult {
  run_id: string; aoi_id: string; params: ScenarioParams; created_at: string;
  rain_series_mm_h: number[]; rain_label: string;
  stage_by_reach_m: Record<string, number[]>;
  flooded_area_km2_by_hour: number[];
  depth_png_urls: string[]; lsi_png_url: string;
  overlay_bounds: [number, number, number, number]; overlay_corners: LonLat[];
  exposure: ExposureSummary; triage: TriageRow[];
  roads_geojson_url: string; routes_geojson_url: string;
  bridges: BridgeStatus[]; shelters: ShelterResult[];
  capacity_gap_people: number;
  assembly_points: { id: string; name: string; lon: number; lat: number; capacity: number }[];
  staging_points: { id: string; lon: number; lat: number; reason: string; near_cluster?: string }[];
  routes: RouteSummary[];
  people_to_evacuate: number;
  hotspots: Hotspot[];
  warnings: string[];
  timings_s: Record<string, number>;
  methods?: Record<string, any>;
  advisory_id?: string | null;
  drains?: DrainPoint[];
  ponding_png_url?: string;
  start_local?: string | null;
  evac_window_h?: number | null;
  demand_breakdown?: { flood?: number; landslide?: number; both?: number };
  demand_range?: number[];
  gap_range?: number[];
}
export interface DrainPoint { id: string; lon: number; lat: number; type: string; name: string; priority: number; photo_condition: string | null;
  exposed_people_300m: number; ponding: number; fsi: number; waterway_id: string }

export interface Forecast {
  hourly: { time: string; local_date: string; local_hour: number; precip_mm: number }[];
  daily: { date: string; precip_mm: number }[];
  alerts: unknown[];
  worst_day_index: number;
  past_90d: { date: string; precip_mm: number | null }[];
  screening: { date: string; precip_mm: number; max_stage_m: number; badge: "low" | "elevated" | "high" }[];
  screening_note: string;
  provider: string;
  attribution: string;
  warnings: string[];
}

export interface Recommendation {
  id: string; horizon: "immediate" | "seasonal" | "structural"; priority: "P1" | "P2" | "P3"; action: string;
  location_label: string; evidence_ids: string[]; why: string; confidence: "low" | "medium" | "high"; lonlat?: LonLat | null;
  owner?: string; act_by_hour?: number | null; act_by?: string;
}
export interface Review { state: "draft" | "reviewed" | "approved"; by?: string; designation?: string; verified?: boolean; at?: string; note?: string }
export interface Supply { item: string; quantity: number; quantity_high: number; unit: string; basis: string }
export interface Translation {
  lang: string; version: number; headline: string; summary: string; disclaimer: string; limitations: string[]; supplies: string[];
  recommendations: Record<string, { id: string; action: string; location_label: string; why: string; act_by: string }>; kept_english: string[];
}
export interface Advisory {
  status?: "pending" | "ready" | "error"; error?: string;
  advisory_id: string; run_id: string; headline: string;
  key_numbers: { label: string; value: number; unit: string; evidence_id: string; rounded?: number | null; range?: number[] | null }[];
  recommendations: Recommendation[]; limitations: string[]; disclaimer: string;
  generated_by: "gemini" | "rules_fallback"; dropped: { action: string; reason: string }[]; model: string;
  summary?: string; start_local?: string | null; evac_window_h?: number | null; breakdown?: { flood?: number; landslide?: number; both?: number };
  supplies?: Supply[]; supply_days?: number; version?: number; last_version?: number; approved_version?: number;
  review?: Review; translations?: Record<string, Translation>; created_at?: string;
}
export interface AdvisoryVersion { version: number; created_at: string; generated_by: string; review: Review; headline: string }
export interface PlanResponse { params: ScenarioParams; diff: Record<string, [unknown, unknown]>; explanation: string }
export interface ChatResponse { reply: string; new_run_id: string | null; tools_called: string[] }
export interface HistoryAoi {
  gfd_events: { start: string; end: string; cause: string; dead: number; displaced: number; severity: number; flooded_km2_in_area: number }[];
  landslides: { lon: number; lat: number; date: string; title: string; type: string; trigger: string; fatalities: number | null; location_accuracy: string; source_url: string }[];
  agreement_pct: number | null; gfd_cells: number; note?: string;
  web?: { type: string; date: string; place: string; summary: string; source_urls: string[]; marker: { lat: number; lng: number } | null }[];
  web_sources?: { title: string; uri: string }[]; search_entry_point?: string; web_label?: string;
  labels?: Record<string, string>;
}
export interface HistoryIndia { gfd_tiles: string; landslides: { lon: number; lat: number; date: string; fatalities: number; type: string }[]; labels: Record<string, string>; note: string }
export interface PhotoDoc {
  photo_id: string; aoi_id: string; kind: "building" | "drain"; lon: number; lat: number; result: Record<string, any>;
  accepted: boolean; message: string; linked_bid?: string; previous_class?: string; override_class?: string; created_at: string;
  link_distance_m?: number | null; model?: string;
}
export interface VerificationItem { bid: string; lon: number; lat: number; current_class: string; score: number; people: number }
