import { useEffect, useMemo, type ReactNode } from "react";
import { APIProvider, ColorScheme, ControlPosition, Map, useMap } from "@vis.gl/react-google-maps";
import { GoogleMapsOverlay } from "@deck.gl/google-maps";
import type { Layer } from "@deck.gl/core";

const KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string;
const MAP_ID = import.meta.env.VITE_MAP_ID as string;

export type MapType = "roadmap" | "hybrid" | "terrain";

/** Attaches a deck.gl overlay to the current Google map and keeps its layers in sync. */
export function useDeckOverlay(layers: Layer[]) {
  const map = useMap();
  const overlay = useMemo(() => new GoogleMapsOverlay({ interleaved: true }), []);
  useEffect(() => {
    if (!map) return;
    overlay.setMap(map);
    return () => overlay.setMap(null);
  }, [map, overlay]);
  useEffect(() => {
    overlay.setProps({ layers });
  }, [overlay, layers]);
}

function DeckLayers({ layers }: { layers: Layer[] }) {
  useDeckOverlay(layers);
  return null;
}

export function MapProvider({ children }: { children: ReactNode }) {
  return <APIProvider apiKey={KEY} language="en" region="IN">{children}</APIProvider>;
}

export function MapCanvas({ center, zoom, layers = [], children, mapTypeId = "hybrid", streetView = true }: {
  center: { lat: number; lng: number }; zoom: number; layers?: Layer[]; children?: ReactNode; mapTypeId?: MapType; streetView?: boolean;
}) {
  return (
    <div className="map-wrap">
      <Map defaultCenter={center} defaultZoom={zoom} mapId={MAP_ID} mapTypeId={mapTypeId} gestureHandling="greedy"
        disableDefaultUI zoomControl zoomControlOptions={{ position: ControlPosition.RIGHT_BOTTOM }}
        streetViewControl={streetView} streetViewControlOptions={{ position: ControlPosition.RIGHT_BOTTOM }}
        colorScheme={ColorScheme.FOLLOW_SYSTEM} clickableIcons={false} style={{ width: "100%", height: "100%" }}>
        <DeckLayers layers={layers} />
        {children}
      </Map>
    </div>
  );
}

type BBox = [number, number, number, number];
type Pad = { top: number; right: number; bottom: number; left: number };

/** Red outline of the simulated area with everything outside it dimmed (like a Google Maps place outline). Fits the
 *  view to the area whenever `fitKey` changes. Drawn with native google.maps.Polygon, above the deck.gl layers. */
export function AreaOutline({ bbox, fitKey, padding = 48, dim = true, color = "#d93025" }: {
  bbox: BBox | null | undefined; fitKey?: unknown; padding?: number | Pad; dim?: boolean; color?: string;
}) {
  const map = useMap();
  const key = bbox?.join(",");
  useEffect(() => {
    if (!map || !bbox) return;
    const [w, s, e, n] = bbox;
    const ring = [{ lat: s, lng: w }, { lat: s, lng: e }, { lat: n, lng: e }, { lat: n, lng: w }];
    const world = [{ lat: 85, lng: -179.9 }, { lat: 85, lng: 0 }, { lat: 85, lng: 179.9 }, { lat: -85, lng: 179.9 }, { lat: -85, lng: 0 }, { lat: -85, lng: -179.9 }];
    const mask = dim ? new google.maps.Polygon({ map, paths: [world, [...ring].reverse()], strokeWeight: 0, fillColor: "#000", fillOpacity: 0.28, clickable: false, zIndex: 1 }) : null;
    const halo = new google.maps.Polygon({ map, paths: ring, strokeColor: "#ffffff", strokeOpacity: 0.9, strokeWeight: 6, fillOpacity: 0, clickable: false, zIndex: 2 });
    const line = new google.maps.Polygon({ map, paths: ring, strokeColor: color, strokeOpacity: 1, strokeWeight: 3, fillOpacity: 0, clickable: false, zIndex: 3 });
    return () => { mask?.setMap(null); halo.setMap(null); line.setMap(null); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key, dim, color]);
  useEffect(() => {
    if (!map || !bbox) return;
    map.fitBounds({ west: bbox[0], south: bbox[1], east: bbox[2], north: bbox[3] }, padding);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key, fitKey]);
  return null;
}
