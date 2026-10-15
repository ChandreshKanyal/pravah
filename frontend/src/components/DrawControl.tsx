import { useEffect, useRef } from "react";
import { useMap } from "@vis.gl/react-google-maps";
import { TerraDraw, TerraDrawPolygonMode, TerraDrawRectangleMode, TerraDrawRenderMode } from "terra-draw";
import { TerraDrawGoogleMapsAdapter } from "terra-draw-google-maps-adapter";

export type DrawMode = "rectangle" | "polygon" | "point" | null;

/**
 * Terra Draw on the Google map (the Maps JS Drawing Library was removed in May 2026).
 * Calls onFinish with the drawn polygon and returns to idle. "point" mode uses a plain map click.
 */
export default function DrawControl({ mode, onFinish, onPoint }: {
  mode: DrawMode;
  onFinish?: (poly: GeoJSON.Polygon) => void;
  onPoint?: (lng: number, lat: number) => void;
}) {
  const map = useMap();
  const drawRef = useRef<TerraDraw | null>(null);
  const finishRef = useRef(onFinish);
  const pointRef = useRef(onPoint);
  finishRef.current = onFinish;
  pointRef.current = onPoint;

  useEffect(() => {
    if (!map) return;
    const draw = new TerraDraw({
      adapter: new TerraDrawGoogleMapsAdapter({ lib: google.maps, map, coordinatePrecision: 6 }),
      modes: [
        new TerraDrawRectangleMode({ styles: { fillColor: "#ffffff", fillOpacity: 0.15, outlineColor: "#ffd60a", outlineWidth: 2 } }),
        new TerraDrawPolygonMode({ styles: { fillColor: "#d7191c", fillOpacity: 0.2, outlineColor: "#d7191c", outlineWidth: 2 } }),
        new TerraDrawRenderMode({ modeName: "idle", styles: {} }),
      ],
    });
    const listener = map.addListener("projection_changed", () => undefined);
    const start = () => {
      draw.start();
      draw.setMode("idle");
      draw.on("finish", (id) => {
        const f = draw.getSnapshotFeature(id);
        if (f && f.geometry.type === "Polygon") finishRef.current?.(f.geometry as GeoJSON.Polygon);
        draw.clear();
        draw.setMode("idle");
      });
      drawRef.current = draw;
    };
    const idle = google.maps.event.addListenerOnce(map, "idle", start);
    return () => {
      idle.remove();
      listener.remove();
      if (drawRef.current) drawRef.current.stop();
      drawRef.current = null;
    };
  }, [map]);

  useEffect(() => {
    const d = drawRef.current;
    if (d) d.setMode(mode === "rectangle" || mode === "polygon" ? mode : "idle");
  }, [mode]);

  useEffect(() => {
    if (!map || mode !== "point") return;
    map.setOptions({ draggableCursor: "crosshair" });
    const l = map.addListener("click", (e: google.maps.MapMouseEvent) => {
      if (e.latLng) pointRef.current?.(e.latLng.lng(), e.latLng.lat());
    });
    return () => {
      l.remove();
      map.setOptions({ draggableCursor: null });
    };
  }, [map, mode]);

  return null;
}

export function bboxOf(poly: GeoJSON.Polygon): [number, number, number, number] {
  const xs = poly.coordinates[0].map((c) => c[0]);
  const ys = poly.coordinates[0].map((c) => c[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

export function bboxKm([w, s, e, n]: [number, number, number, number]): [number, number] {
  const latc = ((s + n) / 2) * (Math.PI / 180);
  return [(e - w) * 111.32 * Math.cos(latc), (n - s) * 110.57];
}
