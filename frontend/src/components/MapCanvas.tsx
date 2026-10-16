import { useEffect, useMemo, type ReactNode } from "react";
import { APIProvider, ColorScheme, ControlPosition, Map, useMap } from "@vis.gl/react-google-maps";
import { GoogleMapsOverlay } from "@deck.gl/google-maps";
import type { Layer } from "@deck.gl/core";

const KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string;
const MAP_ID = import.meta.env.VITE_MAP_ID as string;

export type MapType = "roadmap" | "hybrid" | "terrain";

/** Attaches a deck.gl overlay to the current Google map and keeps its layers in sync.
 *  Non-interleaved (deck draws on its own canvas above the map): in deck.gl 9.4 interleaved mode on vector maps, the
 *  positioning overlay can create the Deck before the WebGL overlay hands over the map's GL context, leaving deck on a
 *  default 300x150 canvas (layers clipped to the top-left corner; seen in Chrome and Safari, 16-17 Oct). */
export function useDeckOverlay(layers: Layer[]) {
  const map = useMap();
  const overlay = useMemo(() => new GoogleMapsOverlay({ interleaved: false }), []);
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

/** Fits the view to the simulated area whenever the box or `fitKey` changes (the outline itself is `areaLayers`). */
export function AreaOutline({ bbox, fitKey, padding = 48 }: { bbox: BBox | null | undefined; fitKey?: unknown; padding?: number | Pad }) {
  const map = useMap();
  const key = bbox?.join(",");
  useEffect(() => {
    if (!map || !bbox) return;
    map.fitBounds({ west: bbox[0], south: bbox[1], east: bbox[2], north: bbox[3] }, padding);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key, fitKey]);
  return null;
}
