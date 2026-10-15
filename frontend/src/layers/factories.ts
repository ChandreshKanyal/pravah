// deck.gl layer factories per data type (S16.8 colours).
import { BitmapLayer, GeoJsonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import type { Layer } from "@deck.gl/core";
import { apiUrl } from "../api/client";
import type { LonLat } from "../types/api";

type RGBA = [number, number, number, number];
export const COLORS = {
  open: [140, 140, 140, 200] as RGBA,
  closesLater: [245, 140, 30, 230] as RGBA,
  closed: [215, 25, 28, 230] as RGBA,
  route: [0, 150, 136, 220] as RGBA,
  shelter: [33, 102, 172, 255] as RGBA,
  shelterOff: [120, 120, 120, 255] as RGBA,
  assembly: [77, 175, 74, 255] as RGBA,
  medical: [228, 26, 28, 255] as RGBA,
  staging: [152, 78, 163, 255] as RGBA,
  hotspot: [255, 255, 255, 255] as RGBA,
  crowd: [255, 127, 0, 255] as RGBA,
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
      getColor: [255, 255, 255, 255], outlineWidth: 3, outlineColor: [0, 0, 0, 220], fontSettings: { sdf: true },
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
