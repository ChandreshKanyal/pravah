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
}

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
}

export const defaultParams = (aoi_id: string): ScenarioParams => ({
  aoi_id, rain_source: "historical_extreme", forecast_day_index: null, manual_intensity_mm_h: 50, duration_h: 4,
  hyetograph: "constant", worst_multiplier: 1.5, best_multiplier: 0.5, river_offset_m: 0, manning_n: 0.04,
  pop_multiplier: 1, pop_total_override: null, disabled_shelter_ids: [], extra_shelters: [], blocked_polygons: [],
  travel_mode: "walk", evac_start_hour: 1, vehicle_depth_limit_m: 0.3, walk_depth_limit_m: 0.5,
  bridge_cut_stage_m: 3, max_travel_min: 60, sqm_per_person: 3.5,
});

export interface ExposureSummary {
  total_pop: number;
  exposed_pop_by_hour: number[];
  exposed_by_depth_band: Record<string, number>;
  landslide_exposed_pop_by_hour: number[];
  buildings_by_risk: Record<string, number>;
  clusters: { id: string; centroid: LonLat; people: number; max_depth: number; risk: number; risk_class: string; dominant_class: string }[];
}

export interface TriageRow { structure_class: string; risk_class: string; buildings: number; people: number }
export interface ShelterResult { id: string; name: string; kind: string; lon: number; lat: number; capacity: number; assigned: number; spare: number; status: string; note: string; capacity_confidence: string }
export interface BridgeStatus { id: string; name: string; lon: number; lat: number; first_closed_hour: number | null; reason: string | null }
export interface RouteSummary { from_node: number; to_shelter: string; people: number; eta_min: number; passable_until_h: number | null; use_now_gone_soon: boolean }

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
}

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
