// deck.gl layer factories. One colour = one meaning across the map, the legend (MapLegend), the layer panel swatches and
// the Results chips; states that differ by colour also differ by a second cue (dash, width, glyph or shape), so they read
// without colour (SPEC S16.8: accessible, never colour alone).
import { BitmapLayer, IconLayer, PathLayer, PolygonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { ClipExtension, CollisionFilterExtension, PathStyleExtension } from "@deck.gl/extensions";
import type { Layer } from "@deck.gl/core";
import { apiUrl } from "../api/client";
import type { LonLat } from "../types/api";

export type RGBA = [number, number, number, number];
export const COLORS = {
  // road network state at the selected hour (roads, bridges, routes)
  open: [154, 160, 166, 220] as RGBA,        // grey #9aa0a6, thin: open
  closesLater: [242, 153, 0, 245] as RGBA,   // orange #f29900: still open, closes later in the scenario
  closed: [217, 48, 37, 245] as RGBA,        // red #d93025, dashed and thicker: closed at this hour
  casing: [32, 33, 36, 150] as RGBA,         // dark edge under closing roads so they read on satellite and shaded layers
  route: [0, 137, 123, 235] as RGBA,         // teal #00897b, width = people; dashed and faded once a road on it closes
  // places: each also has its own marker shape (see drawMarker)
  shelter: [26, 115, 232, 255] as RGBA,      // blue #1a73e8 circle with a house: shelter people are sent to
  candidate: [128, 134, 139, 255] as RGBA,   // grey ring with a grey house: candidate shelter, not used
  assembly: [52, 168, 83, 255] as RGBA,      // green #34a853 square: assembly point
  staging: [147, 52, 230, 255] as RGBA,      // purple #9334e6 diamond: staging point for response teams
  medical: [194, 24, 91, 255] as RGBA,       // magenta #c2185b cross on white: hospital or clinic
  drain: [121, 85, 72, 255] as RGBA,         // brown #795548 down-triangle: drain to inspect
  hotspot: [23, 78, 166, 255] as RGBA,       // navy target: flow hotspot (on the streams layer)
  crowd: [251, 188, 4, 255] as RGBA,         // yellow #fbbc04: crowding hotspot (same family as the crowding shading)
  webReport: [60, 64, 67, 255] as RGBA,      // charcoal #3c4043: web report of a past event
  blocked: [217, 48, 37, 255] as RGBA,       // area you blocked: its roads close, so it shares the "closed" red
  fix: [0, 131, 143, 255] as RGBA,           // dark cyan #00838f circle with a wrench: improvement to make before the rain
  // fixed in the backend overlay PNGs (backend/app/engines/render.py); listed so the legend can match them
  water: [47, 109, 181, 255] as RGBA,        // WATER_COLOR #2f6db5: permanent water, drawn with flood depth
  stream: [8, 48, 107, 255] as RGBA,         // streams.png ("blues" colormap at 1) #08306b
};
export const css = (c: readonly number[], a?: number) => `rgba(${c[0]},${c[1]},${c[2]},${a ?? (c[3] ?? 255) / 255})`;

/** Colour ramps of the backend PNGs (render.py), low to high. */
export const RAMPS = {
  depth: ["#c6dbef", "#9ecae1", "#6baed6", "#3182bd", "#08519c"],  // DEPTH_COLORS at 0.05 / 0.5 / 1 / 1.5 / 3 m
  sus: ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"],    // SUSCEPT_COLORS, classes 1-5
  ponding: ["#9ecae1", "#3182bd", "#08306b"],                       // fill < 30 % / >= 30 % / >= 70 %
  hand: ["#08306b", "#4292c6", "#c6dbef", "#ffffff"],               // "hand" colormap, 0 -> 20 m
  crowd: ["#ffffb2", "#feb24c", "#f03b20", "#800026"],              // "risk" colormap
  traffic: ["#63d668", "#ff974d", "#f23c32", "#811f1f"],            // Google live traffic (display only)
};

/** How strong each shaded layer looks: bitmap opacity here x PNG alpha in render.py. The legend uses the same product. */
export const RASTER = {
  depth: { opacity: 0.9, alpha: 210 }, ponding: { opacity: 0.75, alpha: 210 },
  fsi: { opacity: 0.65, alpha: 170 }, hand: { opacity: 0.65, alpha: 200 },
  crowd: { opacity: 0.65, alpha: 200 }, streams: { opacity: 0.9, alpha: 230 },
};
export type RasterKey = keyof typeof RASTER;
export const rasterAlpha = (k: RasterKey) => RASTER[k].opacity * RASTER[k].alpha / 255;

/** Line styles shared by the map and the legend. Dash = [dash, gap] in line widths (PathStyleExtension). */
export type LineStyle = { color: RGBA; width: number; casing?: number; dash?: [number, number] };
export const LINES = {
  roadOpen: { color: COLORS.open, width: 2 },
  roadLater: { color: COLORS.closesLater, width: 3, casing: 5 },
  roadClosed: { color: COLORS.closed, width: 4, casing: 6, dash: [2.5, 1.5] },
  roadCut: { color: [217, 48, 37, 150] as RGBA, width: 1.5 },                       // rest of a stretch blocked at a point
  route: { color: COLORS.route, width: 5 },                                      // map: 2-10 px by people
  routeClosed: { color: [0, 137, 123, 160] as RGBA, width: 5, dash: [1.6, 1.2] },
  stream: { color: COLORS.stream, width: 2 },
} satisfies Record<string, LineStyle>;

export type RoadState = "open" | "later" | "closed";
/** first_closed_hour is the first hour the road is closed (closed from then on; water never recedes in a scenario). */
export const roadState = (firstClosed: number | null | undefined, hour: number): RoadState =>
  firstClosed == null ? "open" : firstClosed <= hour ? "closed" : "later";
export const STATE_LINE: Record<RoadState, LineStyle> = { open: LINES.roadOpen, later: LINES.roadLater, closed: LINES.roadClosed };
/** Plain words for the backend closure reasons (tooltips and Results). */
export const REASON: Record<string, string> = { flood: "flooded", bridge: "bridge closed", blocked: "blocked by you",
  overtopped: "river over the deck", construction: "under construction (OSM)", closed: "closed to traffic (OSM)", disused: "disused (OSM)" };
/** One line on a bridge's height and how high the river gets, for tooltips and lists. */
export function deckLine(b: { deck_m?: number; deck_source?: string; peak_vs_deck_m?: number | null; status?: string }): string {
  if (b.status && b.status !== "open") return "";
  if (b.deck_m == null) return "";
  const deck = b.deck_source === "minimum" ? `deck at least ${b.deck_m} m above the normal river (too low for the terrain data to measure)` : `deck about ${b.deck_m} m above the normal river`;
  const peak = b.peak_vs_deck_m == null ? "" : b.peak_vs_deck_m >= 0 ? `; at the peak the river is ${b.peak_vs_deck_m} m over the deck` : `; at the peak the river stays ${(-b.peak_vs_deck_m).toFixed(1)} m below the deck`;
  return deck + peak;
}

const RENDER_V = "2";  // bump when backend/app/engines/render.py changes so browsers drop cached overlay PNGs

export type BBox = [number, number, number, number];
const CLIP = new ClipExtension();
/** Props that cut a layer at the simulated-area box: the grid's 3 km hydrology buffer is computed but not counted, so
 *  water and closures out there would only clutter the map. */
const clipTo = (box?: BBox | null) => (box ? { extensions: [CLIP], clipBounds: box } : {});

export const overlayUrl = (url: string) => apiUrl(url) + (url.includes("?") ? "&" : "?") + "v=" + RENDER_V;

/** Overlay PNG on the map. `image` may be a preloaded bitmap: hourly frames then swap in one layer without a blank flash. */
export function bitmap(id: string, url: string, corners: LonLat[], opacity = 0.85, clip?: BBox | null, image?: ImageBitmap | null): Layer {
  // 4 corners (bottom-left, top-left, top-right, bottom-right) correct the UTM grid rotation.
  return new BitmapLayer({ id, image: image ?? overlayUrl(url), bounds: corners as any, opacity, pickable: false,
    ...clipTo(clip) } as any);
}

// ---------- lines ----------
export type PathDatum = { path: LonLat[]; p: Record<string, any> };
const pathCache = new WeakMap<object, PathDatum[]>();
/** GeoJSON lines -> PathLayer rows (cached per collection); rows with a first closure come last so they draw on top. */
function toPaths(fc: GeoJSON.FeatureCollection): PathDatum[] {
  let out = pathCache.get(fc);
  if (out) return out;
  out = [];
  for (const f of fc.features as any[]) {
    const g = f.geometry;
    if (g?.type === "LineString") out.push({ path: g.coordinates, p: f.properties ?? {} });
    else if (g?.type === "MultiLineString") for (const c of g.coordinates) out.push({ path: c, p: f.properties ?? {} });
  }
  out.sort((a, b) => Number(a.p.first_closed_hour != null) - Number(b.p.first_closed_hour != null));
  pathCache.set(fc, out);
  return out;
}
const DASH = new PathStyleExtension({ dash: true });

/** Cut a path at length fractions [a, b] (planar lon/lat lengths with a latitude correction; fine over a few km). */
function slicePath(path: LonLat[], a: number, b: number): LonLat[] {
  const k = Math.cos(((path[0]?.[1] ?? 0) * Math.PI) / 180);
  const cum = [0];
  for (let i = 1; i < path.length; i++) cum.push(cum[i - 1] + Math.hypot((path[i][0] - path[i - 1][0]) * k, path[i][1] - path[i - 1][1]));
  const L = cum[cum.length - 1] || 1, A = a * L, B = b * L;
  const at = (d: number): LonLat => {
    let i = cum.findIndex((c) => c >= d);
    if (i <= 0) return path[Math.max(0, i)];
    const t = (d - cum[i - 1]) / ((cum[i] - cum[i - 1]) || 1);
    return [path[i - 1][0] + t * (path[i][0] - path[i - 1][0]), path[i - 1][1] + t * (path[i][1] - path[i - 1][1])];
  };
  const out: LonLat[] = [at(A)];
  for (let i = 0; i < path.length; i++) if (cum[i] > A && cum[i] < B) out.push(path[i]);
  out.push(at(B));
  return out;
}

type RoadRow = PathDatum & { piece?: boolean; cut?: boolean };
const rowCache = new WeakMap<object, RoadRow[]>();
/** Rows to draw: every edge, plus the hazard pieces of closing edges (where the flooded dip is). An edge with
 *  pieces is marked `cut`: once closed, only its pieces read as closed and the rest as "no through road". */
function roadRows(fc: GeoJSON.FeatureCollection): RoadRow[] {
  let out = rowCache.get(fc);
  if (out) return out;
  const base = toPaths(fc);
  out = base.map((d) => ({ ...d, cut: Array.isArray(d.p.hazard) && d.p.hazard.length > 0 }));
  for (const d of base) {
    if (!Array.isArray(d.p.hazard)) continue;
    const h = d.p.hazard as number[];  // flat [a0, b0, a1, b1, ...] length fractions
    for (let i = 0; i + 1 < h.length; i += 2) if (h[i + 1] > h[i]) out.push({ path: slicePath(d.path, h[i], h[i + 1]), p: d.p, piece: true });
  }
  rowCache.set(fc, out);
  return out;
}

/** Road status at `hour`: open (thin grey), closes later (orange), closed (red, dashed, thicker); closing roads get a dark
 *  edge. On edges whose hazard location is known only those pieces take the state; the rest of a closed edge is a thin red
 *  "no through road" line (a flooded dip 300 m long does not make an 8 km stretch flooded). */
export function roadsLayers(id: string, fc: GeoJSON.FeatureCollection, hour: number, clip?: BBox | null): Layer[] {
  const data = roadRows(fc);
  const st = (d: RoadRow): LineStyle => {
    const s = roadState(d.p.first_closed_hour, hour);
    if (d.cut && !d.piece) return s === "closed" ? LINES.roadCut : LINES.roadOpen;
    return STATE_LINE[s];
  };
  const closing = data.filter((d) => d.p.first_closed_hour != null && (d.piece || !d.cut));
  return [
    new PathLayer<RoadRow>({
      id: `${id}-edge`, data: closing, getPath: (d: RoadRow) => d.path as any, widthUnits: "pixels", jointRounded: true, capRounded: true,
      getColor: COLORS.casing, getWidth: (d: RoadRow) => st(d).casing ?? 0, updateTriggers: { getWidth: hour }, pickable: false, ...clipTo(clip),
    } as any),
    new PathLayer<RoadRow>({
      id, data, pickable: true, getPath: (d: RoadRow) => d.path as any, widthUnits: "pixels", jointRounded: true,
      getColor: (d: RoadRow) => st(d).color, getWidth: (d: RoadRow) => st(d).width, getDashArray: (d: RoadRow) => st(d).dash ?? [0, 0], dashJustified: true,
      extensions: clip ? [DASH, CLIP] : [DASH], clipBounds: clip ?? undefined, updateTriggers: { getColor: hour, getWidth: hour, getDashArray: hour },
    } as any),
  ];
}

/** True when a road on the route has closed by `hour` (the route is no longer passable). */
export const routeClosed = (passableUntil: number | null | undefined, hour: number) => passableUntil != null && passableUntil <= hour;

/** Evacuation routes, width = people; dashed and faded from the hour a road on them closes. */
export function routesLayer(id: string, fc: GeoJSON.FeatureCollection, hour: number): Layer {
  const data = toPaths(fc);
  const max = Math.max(1, ...data.map((d) => d.p.people ?? 0));
  const st = (d: PathDatum) => (routeClosed(d.p.passable_until_h, hour) ? LINES.routeClosed : LINES.route);
  return new PathLayer<PathDatum>({
    id, data, pickable: true, getPath: (d: PathDatum) => d.path as any, widthUnits: "pixels", jointRounded: true, capRounded: true,
    getColor: (d: PathDatum) => st(d).color, getWidth: (d: PathDatum) => 2 + 8 * ((d.p.people ?? 0) / max),
    getDashArray: (d: PathDatum) => (st(d) as LineStyle).dash ?? [0, 0],
    dashJustified: true, extensions: [DASH], updateTriggers: { getColor: hour, getDashArray: hour },
  } as any);
}

// ---------- markers ----------
export type Marker = "shelter" | "candidate" | "assembly" | "staging" | "medical" | "drain" | "bridgeLater" | "bridgeClosed"
  | "hotspot" | "crowd" | "webReport" | "fix";
const MARKERS: Marker[] = ["shelter", "candidate", "assembly", "staging", "medical", "drain", "bridgeLater", "bridgeClosed",
  "hotspot", "crowd", "webReport", "fix"];
const CELL = 64;  // atlas cell in px; markers display at 13-34 px, so this is about 2x for sharp edges

function rounded(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}

/** One marker: a shape with a white ring and a faint dark edge (reads on satellite, light and dark maps), then a glyph. */
function drawMarker(g: CanvasRenderingContext2D, m: Marker) {
  const WHITE = "#ffffff", INK = "#202124", c = css;
  const shape = (kind: "circle" | "square" | "diamond" | "down" | "up", fill: string, ring = WHITE, ringW = 6) => {
    g.beginPath();
    if (kind === "circle") g.arc(32, 32, 26.5, 0, Math.PI * 2);
    else if (kind === "square") rounded(g, 9, 9, 46, 46, 9);
    else if (kind === "diamond") { g.moveTo(32, 6); g.lineTo(58, 32); g.lineTo(32, 58); g.lineTo(6, 32); g.closePath(); }
    else if (kind === "down") { g.moveTo(7, 13); g.lineTo(57, 13); g.lineTo(32, 56); g.closePath(); }
    else { g.moveTo(32, 7); g.lineTo(57, 52); g.lineTo(7, 52); g.closePath(); }
    g.lineJoin = "round";
    g.lineWidth = ringW + 3; g.strokeStyle = "rgba(0,0,0,0.32)"; g.stroke();
    g.lineWidth = ringW; g.strokeStyle = ring; g.stroke();
    g.fillStyle = fill; g.fill();
  };
  const house = (fill: string) => {
    g.beginPath(); g.moveTo(32, 15); g.lineTo(48, 29.5); g.lineTo(43.5, 29.5); g.lineTo(43.5, 46); g.lineTo(20.5, 46);
    g.lineTo(20.5, 29.5); g.lineTo(16, 29.5); g.closePath(); g.fillStyle = fill; g.fill();
  };
  const bar = (fill: string, vertical = false) => { g.beginPath(); vertical ? rounded(g, 27, 15, 10, 34, 2.5) : rounded(g, 15, 27, 34, 10, 2.5); g.fillStyle = fill; g.fill(); };
  switch (m) {
    case "shelter": shape("circle", c(COLORS.shelter)); house(WHITE); break;
    case "candidate": shape("circle", WHITE, c(COLORS.candidate), 6); house(c(COLORS.candidate)); break;
    case "assembly": shape("square", c(COLORS.assembly)); break;
    case "staging": shape("diamond", c(COLORS.staging)); break;
    case "medical": shape("circle", WHITE, c(COLORS.medical), 6); bar(c(COLORS.medical)); bar(c(COLORS.medical), true); break;
    case "drain": shape("down", c(COLORS.drain)); break;
    case "bridgeLater":  // warning: dark "!" on orange
      shape("circle", c(COLORS.closesLater)); g.beginPath(); rounded(g, 28, 14, 8, 22, 3); g.fillStyle = INK; g.fill();
      g.beginPath(); g.arc(32, 44, 4.6, 0, Math.PI * 2); g.fill(); break;
    case "bridgeClosed": shape("circle", c(COLORS.closed)); bar(WHITE); break;  // no-entry sign
    case "hotspot":
      shape("circle", WHITE, c(COLORS.hotspot), 8); g.beginPath(); g.arc(32, 32, 9, 0, Math.PI * 2); g.fillStyle = c(COLORS.hotspot); g.fill(); break;
    case "crowd": shape("circle", c(COLORS.crowd)); break;
    case "webReport": shape("circle", c(COLORS.webReport)); break;
    case "fix": {  // wrench: a ring head with an open jaw on a handle, drawn diagonally
      shape("circle", c(COLORS.fix));
      g.save(); g.translate(32, 32); g.rotate(Math.PI / 4); g.fillStyle = WHITE;
      g.beginPath(); rounded(g, -4, -4, 8, 22, 3); g.fill();
      g.beginPath(); g.arc(0, -10, 9, 0, Math.PI * 2); g.fill();
      g.globalCompositeOperation = "destination-out"; g.beginPath(); rounded(g, -3.5, -22, 7, 13, 1.5); g.fill();
      g.restore();
      // the jaw cut-out removes fill too: redraw the circle edge under it so the marker stays round
      g.save(); g.globalCompositeOperation = "destination-over"; g.beginPath(); g.arc(32, 32, 26.5, 0, Math.PI * 2); g.fillStyle = c(COLORS.fix); g.fill(); g.restore();
      break;
    }
  }
}

let atlas: { url: string; mapping: Record<string, object>; urls: Record<Marker, string> } | null = null;
function getAtlas() {
  if (atlas) return atlas;
  const sheet = document.createElement("canvas");
  sheet.width = CELL * MARKERS.length; sheet.height = CELL;
  const gs = sheet.getContext("2d")!;
  const urls = {} as Record<Marker, string>, mapping: Record<string, object> = {};
  MARKERS.forEach((m, i) => {
    const one = document.createElement("canvas");
    one.width = one.height = CELL;
    drawMarker(one.getContext("2d")!, m);
    urls[m] = one.toDataURL("image/png");
    gs.drawImage(one, i * CELL, 0);
    mapping[m] = { x: i * CELL, y: 0, width: CELL, height: CELL, anchorY: CELL / 2, mask: false };
  });
  atlas = { url: sheet.toDataURL("image/png"), mapping, urls };
  return atlas;
}
/** The marker image as a data URL: the legend, layer panel and Results show exactly what the map draws. */
export const markerUrl = (m: Marker) => getAtlas().urls[m];

const COLLIDE = new CollisionFilterExtension();

/** Point markers with an optional label above (S#, A#, G#, D#...). `trigger` re-evaluates icon and size (e.g. the hour).
 *  `declutter` hides markers that would overlap at the current zoom (higher priority wins), like Google Maps POIs. */
export function markers<T extends { lon: number; lat: number }>(id: string, data: T[], o: {
  icon: Marker | ((d: T) => Marker); size?: number | ((d: T) => number); label?: (d: T) => string; trigger?: unknown;
  declutter?: { priority?: (d: T) => number; spacing?: number };
}): Layer[] {
  const a = getAtlas();
  const size = typeof o.size === "function" ? o.size : () => (o.size as number | undefined) ?? 18;
  const layers: Layer[] = [new IconLayer<T>({
    id, data, pickable: true, iconAtlas: a.url, iconMapping: a.mapping as any, sizeUnits: "pixels",
    getIcon: (typeof o.icon === "function" ? o.icon : () => o.icon) as any, getPosition: (d: T) => [d.lon, d.lat], getSize: size,
    updateTriggers: { getIcon: o.trigger, getSize: o.trigger },
    ...(o.declutter ? {
      extensions: [COLLIDE], collisionGroup: id, getCollisionPriority: o.declutter.priority ?? 0,
      collisionTestProps: { sizeScale: o.declutter.spacing ?? 1.5 },
    } : {}),
  } as any)];
  if (o.label) {
    layers.push(new TextLayer<T>({
      id: `${id}-label`, data, getPosition: (d: T) => [d.lon, d.lat], getText: o.label, getSize: 12,
      getPixelOffset: (d: T) => [0, -(size(d) / 2 + 8)], fontFamily: "Google Sans, Roboto, Arial", fontWeight: 500,
      getColor: [255, 255, 255, 255], outlineWidth: 3, outlineColor: [32, 33, 36, 230], fontSettings: { sdf: true },
      characterSet: "auto", updateTriggers: { getPixelOffset: o.trigger },
    }));
  }
  return layers;
}

/** Plain circle markers (Brief and Field check mini maps, which carry their own keys). */
export function points<T extends { lon: number; lat: number }>(id: string, data: T[], color: RGBA | ((d: T) => RGBA),
  radius: number | ((d: T) => number) = 8, label?: (d: T) => string): Layer[] {
  const layers: Layer[] = [new ScatterplotLayer<T>({
    id, data, pickable: true, radiusUnits: "pixels", stroked: true, lineWidthUnits: "pixels", getLineWidth: 1.5,
    getLineColor: [255, 255, 255, 255], getPosition: (d) => [d.lon, d.lat], getFillColor: color as any, getRadius: radius as any,
    updateTriggers: { getFillColor: [data], getRadius: [data] },
  })];
  if (label) {
    layers.push(new TextLayer<T>({
      id: `${id}-label`, data, getPosition: (d) => [d.lon, d.lat], getText: label, getSize: 12, getPixelOffset: [0, -16],
      fontFamily: "Google Sans, Roboto, Arial", fontWeight: 500,
      getColor: [255, 255, 255, 255], outlineWidth: 3, outlineColor: [32, 33, 36, 230], fontSettings: { sdf: true },
      characterSet: "auto",
    }));
  }
  return layers;
}

/** Areas the user blocked: translucent "closed" red with a solid edge (their roads close from hour 1). */
export function polygonsLayer(id: string, polys: GeoJSON.Polygon[]): Layer {
  return new PolygonLayer({
    id, data: polys.map((g) => ({ p: g.coordinates })), getPolygon: (d: any) => d.p,
    getFillColor: [...COLORS.blocked.slice(0, 3), 60] as RGBA, getLineColor: COLORS.blocked, lineWidthUnits: "pixels", getLineWidth: 2, stroked: true,
    pickable: true,
  });
}

/** Simulated-area outline: dim everything outside the box, then a white dashed border on a dark halo (drawn by deck.gl so it
 *  shares one renderer with the other layers on both vector and raster maps). Put the border above the rasters. */
export function areaLayers(bbox: [number, number, number, number]): { mask: Layer; border: Layer[] } {
  const [w, s, e, n] = bbox;
  const ring: LonLat[] = [[w, s], [e, s], [e, n], [w, n], [w, s]];
  const world: LonLat[] = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
  const mask = new PolygonLayer({ id: "area-mask", data: [{ p: [world, [...ring].reverse()] }], getPolygon: (d: any) => d.p,
    getFillColor: [0, 0, 0, 110], stroked: false, pickable: false, parameters: { depthCompare: "always" } as any });
    // white dashes on a dark outline read on satellite and on light maps alike; red is reserved for closed roads and bridges
  const border: Layer[] = [
    new PathLayer({ id: "area-halo", data: [{ p: ring }], getPath: (d: any) => d.p, getColor: [32, 33, 36, 210], getWidth: 6,
      widthUnits: "pixels", jointRounded: true, pickable: false, parameters: { depthCompare: "always" } as any }),
    new PathLayer({ id: "area-border", data: [{ p: ring }], getPath: (d: any) => d.p, getColor: [255, 255, 255, 255], getWidth: 3,
      widthUnits: "pixels", jointRounded: true, pickable: false, parameters: { depthCompare: "always" } as any,
      getDashArray: [4, 3], dashJustified: true, extensions: [new PathStyleExtension({ dash: true })] } as any),
  ];
  return { mask, border };
}
