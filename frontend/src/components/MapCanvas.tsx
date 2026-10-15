import { useEffect, useMemo, type ReactNode } from "react";
import { APIProvider, Map, useMap } from "@vis.gl/react-google-maps";
import { GoogleMapsOverlay } from "@deck.gl/google-maps";
import type { Layer } from "@deck.gl/core";

const KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string;
const MAP_ID = import.meta.env.VITE_MAP_ID as string;

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
  return <APIProvider apiKey={KEY}>{children}</APIProvider>;
}

export function MapCanvas({ center, zoom, layers = [], children, mapTypeId = "hybrid" }: {
  center: { lat: number; lng: number }; zoom: number; layers?: Layer[]; children?: ReactNode; mapTypeId?: string;
}) {
  return (
    <div className="map-wrap">
      <Map defaultCenter={center} defaultZoom={zoom} mapId={MAP_ID} mapTypeId={mapTypeId} gestureHandling="greedy"
        mapTypeControl streetViewControl fullscreenControl={false} style={{ width: "100%", height: "100%" }}>
        <DeckLayers layers={layers} />
        {children}
      </Map>
    </div>
  );
}
