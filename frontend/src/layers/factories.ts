// deck.gl layer factories per data type (S16.8 colours).
import { BitmapLayer, GeoJsonLayer, PathLayer, PolygonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import type { Layer } from "@deck.gl/core";
import { apiUrl } from "../api/client";
import type { LonLat } from "../types/api";

type RGBA = [number, number, number, number];
export const COLORS = {  // Google palette
  open: [154, 160, 166, 210] as RGBA,
  closesLater: [242, 153, 0, 235] as RGBA,
  closed: [217, 48, 37, 235] as RGBA,
  route: [0, 137, 123, 225] as RGBA,
  shelter: [26, 115, 232, 255] as RGBA,
  shelterOff: [128, 134, 139, 255] as RGBA,
  assembly: [52, 168, 83, 255] as RGBA,
  medical: [234, 67, 53, 255] as RGBA,
  staging: [147, 52, 230, 255] as RGBA,
  hotspot: [255, 255, 255, 255] as RGBA,
  crowd: [251, 188, 4, 255] as RGBA,
};

export function bitmap(id: string, url: string, corners: LonLat[], opacity = 0.85): Layer {
  // 4 corners (bottom-left, top-left, top-right, bottom-right) correct the UTM grid rotation.
  return new BitmapLayer({ id, image: apiUrl(url), bounds: corners as any, opacity, pickable: false });
}

export function roadsLayer(id: string, data: GeoJSON.FeatureCollection, hour: number): Layer {
  return new GeoJsonLayer({
    id, data, pickable: true, lineWidthUnits: "pixels",
    getLineWidth: (f: any) => (f.properties.bridge ? 4 : 2),
    getLineColor: (f: any) => {
      const h = f.properties.first_closed_hour;
      if (h == null) return COLORS.open;
      return h <= hour ? COLORS.closed : COLORS.closesLater;
    },
    updateTriggers: { getLineColor: hour },
  });
}

export function routesLayer(id: string, data: GeoJSON.FeatureCollection): Layer {
  const max = Math.max(1, ...data.features.map((f: any) => f.properties.people));
  return new GeoJsonLayer({
    id, data, pickable: true, lineWidthUnits: "pixels", getLineColor: COLORS.route,
    getLineWidth: (f: any) => 2 + 8 * (f.properties.people / max),
  });
}

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

export function polygonsLayer(id: string, polys: GeoJSON.Polygon[]): Layer {
  return new GeoJsonLayer({
    id, data: { type: "FeatureCollection", features: polys.map((g) => ({ type: "Feature", geometry: g, properties: {} })) } as any,
    getFillColor: [215, 25, 28, 60], getLineColor: [215, 25, 28, 255], lineWidthUnits: "pixels", getLineWidth: 2,
  });
}

/** Simulated-area outline: dim everything outside the box, then a white-haloed red border (drawn by deck.gl so it shares
 *  one renderer with the other layers on both vector and raster maps). Returns [mask, border]; put border last. */
export function areaLayers(bbox: [number, number, number, number]): [Layer, Layer] {
  const [w, s, e, n] = bbox;
  const ring: LonLat[] = [[w, s], [e, s], [e, n], [w, n], [w, s]];
  const world: LonLat[] = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
  const mask = new PolygonLayer({ id: "area-mask", data: [{ p: [world, [...ring].reverse()] }], getPolygon: (d: any) => d.p,
    getFillColor: [0, 0, 0, 64], stroked: false, pickable: false, parameters: { depthCompare: "always" } as any });
    const border = new PathLayer({ id: "area-border", data: [{ p: ring }], getPath: (d: any) => d.p, getColor: [217, 48, 37, 255], getWidth: 4,
    widthUnits: "pixels", widthMinPixels: 4, jointRounded: true, capRounded: true, pickable: false, parameters: { depthCompare: "always" } as any });
  return [mask, border];
}
