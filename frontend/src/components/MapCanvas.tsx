import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { APIProvider, ColorScheme, ControlPosition, Map, useMap } from "@vis.gl/react-google-maps";
import { GoogleMapsOverlay } from "@deck.gl/google-maps";
import type { Layer, PickingInfo } from "@deck.gl/core";
import { useTheme } from "../theme";

const KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string;
const MAP_ID = import.meta.env.VITE_MAP_ID as string;

export type MapType = "roadmap" | "hybrid" | "terrain";

export type Tooltip = (info: PickingInfo) => string | null;

// M3 plain tooltip (inverse surface), offset from the pointer; text only, so OSM names can never inject markup
const TIP_STYLE: Partial<CSSStyleDeclaration> = {
  background: "var(--inverse-surface)", color: "var(--inverse-on-surface)", font: "400 12px/16px var(--font)", padding: "6px 8px",
  borderRadius: "4px", maxWidth: "260px", whiteSpace: "pre-line", marginLeft: "14px", marginTop: "14px", boxShadow: "var(--e2)",
};

/** Attaches a deck.gl overlay to the current Google map and keeps its layers in sync.
 *  Non-interleaved (deck draws on its own canvas above the map): in deck.gl 9.4 interleaved mode on vector maps, the
 *  positioning overlay can create the Deck before the WebGL overlay hands over the map's GL context, leaving deck on a
 *  default 300x150 canvas (layers clipped to the top-left corner; seen in Chrome and Safari, 16-17 Oct). */
export function useDeckOverlay(layers: Layer[], tooltip?: Tooltip, onPick?: (info: PickingInfo) => void) {
  const map = useMap();
  // one overlay (one Deck) per map instance: a theme change creates a new Google map (colorScheme is fixed at creation)
  const overlay = useMemo(() => (map ? new GoogleMapsOverlay({ interleaved: false }) : null), [map]);
  useEffect(() => {
    if (!map || !overlay) return;
    overlay.setMap(map);
    return () => overlay.finalize();
  }, [map, overlay]);
  const handed = useRef<{ overlay: GoogleMapsOverlay | null; layers: Layer[] | null }>({ overlay: null, layers: null });
  useEffect(() => {
    if (!overlay) return;
    // layers already given to an earlier map's Deck were finalized with it and cannot be reused: give a new Deck copies
    const h = handed.current;
    const fresh = h.layers === layers && h.overlay !== null && h.overlay !== overlay ? layers.map((l) => l.clone({})) : layers;
    handed.current = { overlay, layers };
    overlay.setProps({
      layers: fresh,
      getTooltip: tooltip ? (info: PickingInfo) => { const t = info.object ? tooltip(info) : null; return t ? { text: t, style: TIP_STYLE } : null; } : null,
      onClick: onPick ? (info: PickingInfo) => { if (info.object) onPick(info); } : null,
      getCursor: ({ isHovering }: { isHovering: boolean }) => (isHovering && onPick ? "pointer" : "grab"),
    } as any);
  }, [overlay, layers, tooltip, onPick]);
}

function DeckLayers({ layers, tooltip, onPick }: { layers: Layer[]; tooltip?: Tooltip; onPick?: (info: PickingInfo) => void }) {
  useDeckOverlay(layers, tooltip, onPick);
  return null;
}

export function MapProvider({ children }: { children: ReactNode }) {
  return <APIProvider apiKey={KEY} language="en" region="IN">{children}</APIProvider>;
}

export function MapCanvas({ center, zoom, layers = [], children, mapTypeId = "hybrid", streetView = true, tooltip, onPick }: {
  center: { lat: number; lng: number }; zoom: number; layers?: Layer[]; children?: ReactNode; mapTypeId?: MapType; streetView?: boolean;
  tooltip?: Tooltip; onPick?: (info: PickingInfo) => void;
}) {
  // the base map follows the app theme (vector maps only; changing it makes a new map, which re-fits the area)
  const theme = useTheme();
  const scheme = theme === "dark" ? ColorScheme.DARK : theme === "light" ? ColorScheme.LIGHT : ColorScheme.FOLLOW_SYSTEM;
  return (
    <div className="map-wrap">
      <Map defaultCenter={center} defaultZoom={zoom} mapId={MAP_ID} mapTypeId={mapTypeId} gestureHandling="greedy"
        disableDefaultUI zoomControl zoomControlOptions={{ position: ControlPosition.RIGHT_CENTER }}
        streetViewControl={streetView} streetViewControlOptions={{ position: ControlPosition.RIGHT_CENTER }}
        colorScheme={scheme} clickableIcons={false} style={{ width: "100%", height: "100%" }}>
        <DeckLayers layers={layers} tooltip={tooltip} onPick={onPick} />
        {children}
      </Map>
    </div>
  );
}

/** Opens Google Street View at the nearest Google outdoor panorama for a person to look; display only, the imagery is
 *  never analysed. Searches 100 m, then 300 m, then 1 km (spots on river banks are often far from a road with imagery) and
 *  reports how far the view is from the spot through `onFound`, or calls `onNone`. */
export function StreetViewAt({ target, onNone, onFound }: { target: { lon: number; lat: number; t: number } | null; onNone?: () => void;
  onFound?: (metres: number) => void }) {
  const map = useMap();
  useEffect(() => {
    if (!map || !target) return;
    const svc = new google.maps.StreetViewService();
    const at = { lat: target.lat, lng: target.lon };
    const radii = [100, 300, 1000];
    const tryRadius = (k: number) => svc.getPanorama(
      // Google's own outdoor imagery only: user-uploaded photo spheres often render black in the JS API
      { location: at, radius: radii[k], preference: google.maps.StreetViewPreference.NEAREST,
        sources: [google.maps.StreetViewSource.GOOGLE, google.maps.StreetViewSource.OUTDOOR] },
      (data, status) => {
        if (status !== google.maps.StreetViewStatus.OK || !data?.location?.pano) {
          if (k + 1 < radii.length) tryRadius(k + 1); else onNone?.();
          return;
        }
        const sv = map.getStreetView();
        sv.setPano(data.location.pano);
        const from = data.location.latLng;
        // face the spot: bearing from the panorama to the target (geometry library not loaded, so by hand)
        const dLon = from ? (target.lon - from.lng()) * Math.cos((target.lat * Math.PI) / 180) : 0, dLat = from ? target.lat - from.lat() : 0;
        sv.setPov({ heading: (Math.atan2(dLon, dLat) * 180) / Math.PI, pitch: -5 });
        sv.setVisible(true);
        onFound?.(Math.round(Math.hypot(dLon, dLat) * 111_320));
        // a panorama that still fails to load leaves a black screen: close it and say so
        const l = sv.addListener("status_changed", () => {
          if (sv.getStatus() !== google.maps.StreetViewStatus.OK) { sv.setVisible(false); onNone?.(); }
          l.remove();
        });
      });
    tryRadius(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, target]);
  return null;
}

/** Tracks whether Street View is open (from the panel's button or the pegman) and closes it when `closeT` changes. The
 *  map hides Google's default UI, which also hid the panorama's own close button: turn that back on. */
export function StreetViewWatch({ onChange, closeT }: { onChange: (on: boolean) => void; closeT: number }) {
  const map = useMap();
  useEffect(() => {
    if (!map) return;
    const sv = map.getStreetView();
    sv.setOptions({ enableCloseButton: false, addressControl: false, fullscreenControl: false, panControl: true, zoomControl: true });
    const l = sv.addListener("visible_changed", () => onChange(!!sv.getVisible()));
    return () => l.remove();
  }, [map, onChange]);
  useEffect(() => { if (map && closeT) map.getStreetView().setVisible(false); }, [map, closeT]);
  return null;
}

/** Reports the map zoom (rounded) so callers can show detail, such as marker labels, only when zoomed in. */
export function ZoomWatch({ onZoom }: { onZoom: (z: number) => void }) {
  const map = useMap();
  useEffect(() => {
    if (!map) return;
    const h = () => onZoom(Math.round(map.getZoom() ?? 0));
    h();
    const l = map.addListener("zoom_changed", h);
    return () => l.remove();
  }, [map, onZoom]);
  return null;
}

export type Camera = { lat: number; lng: number; zoom: number };
/** Reports where the map is looking each time it comes to rest (saved so the view survives a trip to 3D). */
export function CameraWatch({ onChange }: { onChange: (c: Camera) => void }) {
  const map = useMap();
  useEffect(() => {
    if (!map) return;
    const l = map.addListener("idle", () => {
      const c = map.getCenter(), z = map.getZoom();
      if (c && z != null) onChange({ lat: c.lat(), lng: c.lng(), zoom: z });
    });
    return () => l.remove();
  }, [map, onChange]);
  return null;
}

type BBox = [number, number, number, number];
type Pad = { top: number; right: number; bottom: number; left: number };

/** Fits the view to the simulated area whenever the box or `fitKey` changes (the outline itself is `areaLayers`). */
export function AreaOutline({ bbox, fitKey, padding = 48, keepView }: { bbox: BBox | null | undefined; fitKey?: unknown; padding?: number | Pad; keepView?: boolean }) {
  const map = useMap();
  const key = bbox?.join(",");
  const kept = useRef(!keepView);  // keepView: the first fit is skipped (the map opens where the person left it)
  useEffect(() => {
    if (!map || !bbox) return;
    if (!kept.current) { kept.current = true; return; }
    map.fitBounds({ west: bbox[0], south: bbox[1], east: bbox[2], north: bbox[3] }, padding);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key, fitKey]);
  return null;
}
