"use client";

import { useEffect, useRef, useState } from "react";
import type { Map as MLMap, Marker, GeoJSONSource, MapLayerMouseEvent, Popup } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { LonLat } from "@/lib/types";
import { RISK, type RiskTier } from "@/lib/colors";

export interface MapRoute {
  crew: string;
  color: string;
  coords: LonLat[];
  roadGeometry: boolean;
}
export interface MapStop {
  id: string;
  lon: number;
  lat: number;
  tier: RiskTier;
  planned: boolean;
  title: string;
  detail: string;
  reason: string | null;
  crew: string | null;
}
export interface MapDepot {
  lon: number;
  lat: number;
  label: string;
}
export interface MapVoice {
  id: string;
  lon: number;
  lat: number;
  reason: string | null;
  crew: string | null;
}

interface Props {
  routes: MapRoute[];
  stops: MapStop[];
  depots: MapDepot[];
  voice?: MapVoice[];
  selectedCrew?: string | null;
  onSelectCrew?: (crew: string | null) => void;
  /** Change this to re-centre on a voice ticket. */
  focus?: { lon: number; lat: number; key: string } | null;
  ariaLabel: string;
}

// CARTO Dark Matter: free vector basemap, no API key.
const STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const CALGARY: [number, number] = [-114.07, 51.035];
const CALGARY_BOUNDS: [number, number, number, number] = [-114.28, 50.87, -113.88, 51.2];

const empty = { type: "FeatureCollection" as const, features: [] };

function routesFC(routes: MapRoute[]) {
  return {
    type: "FeatureCollection" as const,
    features: routes
      .filter((r) => r.coords.length > 1)
      .map((r) => ({
        type: "Feature" as const,
        properties: { crew: r.crew, color: r.color },
        geometry: { type: "LineString" as const, coordinates: r.coords },
      })),
  };
}
function stopsFC(stops: MapStop[]) {
  return {
    type: "FeatureCollection" as const,
    features: stops.map((s) => ({
      type: "Feature" as const,
      properties: {
        id: s.id,
        color: RISK[s.tier].color,
        tierRank: s.tier === "high" ? 2 : s.tier === "mid" ? 1 : 0,
        planned: s.planned ? 1 : 0,
        title: s.title,
        detail: s.detail,
        reason: s.reason ?? "",
        crew: s.crew ?? "",
      },
      geometry: { type: "Point" as const, coordinates: [s.lon, s.lat] },
    })),
  };
}
function depotsFC(depots: MapDepot[]) {
  return {
    type: "FeatureCollection" as const,
    features: depots.map((d) => ({
      type: "Feature" as const,
      properties: { label: d.label },
      geometry: { type: "Point" as const, coordinates: [d.lon, d.lat] },
    })),
  };
}

export default function OpsMap({ routes, stops, depots, voice = [], selectedCrew = null, onSelectCrew, focus, ariaLabel }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const markers = useRef<Map<string, Marker>>(new Map());
  const popupRef = useRef<Popup | null>(null);
  const libRef = useRef<typeof import("maplibre-gl") | null>(null);
  const onSelectRef = useRef(onSelectCrew);
  useEffect(() => {
    onSelectRef.current = onSelectCrew;
  }, [onSelectCrew]);

  // init once
  useEffect(() => {
    let cancelled = false;
    let map: MLMap | null = null;
    (async () => {
      try {
        const ml = await import("maplibre-gl");
        if (cancelled || !el.current) return;
        libRef.current = ml;
        ml.setWorkerUrl(new URL("/maplibre/maplibre-gl-worker.mjs", window.location.href).href);
        map = new ml.Map({
          container: el.current,
          style: STYLE,
          center: CALGARY,
          zoom: 10,
          // fit the city limits at any viewport size (1280x720 projector up to 1920x1080)
          bounds: CALGARY_BOUNDS,
          fitBoundsOptions: { padding: 24 },
          attributionControl: { compact: true },
          dragRotate: false,
          pitchWithRotate: false,
        });
        map.addControl(new ml.NavigationControl({ showCompass: false }), "top-right");
        mapRef.current = map;
        map.on("error", (e) => {
          // tile/style errors: keep the overlay working; only fail hard if style never loads
          if (!map?.isStyleLoaded()) setFailed(String(e?.error?.message ?? "map style failed to load"));
        });
        map.on("load", () => {
          if (!map) return;
          setFailed(null);
          map.addSource("routes", { type: "geojson", data: empty });
          map.addSource("stops", { type: "geojson", data: empty });
          map.addSource("depots", { type: "geojson", data: empty });
          map.addLayer({
            id: "routes-casing",
            type: "line",
            source: "routes",
            layout: { "line-join": "round", "line-cap": "round" },
            paint: { "line-color": "#0b0c0e", "line-width": 5, "line-opacity": 0.7 },
          });
          map.addLayer({
            id: "routes",
            type: "line",
            source: "routes",
            layout: { "line-join": "round", "line-cap": "round" },
            paint: { "line-color": ["get", "color"], "line-width": 2.5, "line-opacity": 0.9 },
          });
          map.addLayer({
            id: "stops-unplanned",
            type: "circle",
            source: "stops",
            filter: ["==", ["get", "planned"], 0],
            paint: {
              "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 2, 13, 4],
              "circle-color": ["get", "color"],
              "circle-opacity": 0.45,
            },
          });
          map.addLayer({
            id: "stops-planned",
            type: "circle",
            source: "stops",
            filter: ["==", ["get", "planned"], 1],
            layout: { "circle-sort-key": ["get", "tierRank"] },
            paint: {
              "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 4, 13, 7],
              "circle-color": ["get", "color"],
              "circle-stroke-color": "#0b0c0e",
              "circle-stroke-width": 1.5,
            },
          });
          map.addLayer({
            id: "depots",
            type: "circle",
            source: "depots",
            paint: {
              "circle-radius": 6,
              "circle-color": "#0b0c0e",
              "circle-stroke-color": "#f4f4f5",
              "circle-stroke-width": 2,
            },
          });
          for (const layer of ["stops-planned", "stops-unplanned"]) {
            map.on("mouseenter", layer, () => map && (map.getCanvas().style.cursor = "pointer"));
            map.on("mouseleave", layer, () => map && (map.getCanvas().style.cursor = ""));
            map.on("click", layer, (e: MapLayerMouseEvent) => {
              const f = e.features?.[0];
              if (!f || !map) return;
              const p = f.properties as Record<string, string>;
              const div = document.createElement("div");
              const t = document.createElement("div");
              t.className = "font-semibold text-zinc-50";
              t.textContent = p.title;
              const d = document.createElement("div");
              d.className = "text-zinc-400 text-xs mt-0.5";
              d.textContent = p.detail;
              div.append(t, d);
              if (p.reason) {
                const r = document.createElement("div");
                r.className = "text-zinc-300 text-xs mt-1.5";
                r.textContent = `Why: ${p.reason}`;
                div.append(r);
              }
              popupRef.current?.remove();
              popupRef.current = new ml.Popup({ closeButton: false, maxWidth: "280px", className: "cs-popup" })
                .setLngLat(e.lngLat)
                .setDOMContent(div)
                .addTo(map);
              if (p.crew) onSelectRef.current?.(p.crew);
            });
          }
          map.on("click", "routes", (e: MapLayerMouseEvent) => {
            const c = e.features?.[0]?.properties?.crew;
            if (c) onSelectRef.current?.(c as string);
          });
          map.on("mouseenter", "routes", () => map && (map.getCanvas().style.cursor = "pointer"));
          map.on("mouseleave", "routes", () => map && (map.getCanvas().style.cursor = ""));
          setReady(true);
        });
      } catch (e) {
        setFailed(e instanceof Error ? e.message : "WebGL map could not start");
      }
    })();
    const mk = markers.current;
    return () => {
      cancelled = true;
      mk.forEach((m) => m.remove());
      mk.clear();
      map?.remove();
      mapRef.current = null;
    };
  }, []);

  // data
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource("routes") as GeoJSONSource)?.setData(routesFC(routes));
  }, [ready, routes]);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource("stops") as GeoJSONSource)?.setData(stopsFC(stops));
  }, [ready, stops]);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource("depots") as GeoJSONSource)?.setData(depotsFC(depots));
  }, [ready, depots]);

  // crew isolation
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (selectedCrew) {
      map.setPaintProperty("routes", "line-opacity", ["case", ["==", ["get", "crew"], selectedCrew], 1, 0.12]);
      map.setPaintProperty("routes", "line-width", ["case", ["==", ["get", "crew"], selectedCrew], 4.5, 2]);
      map.setPaintProperty("routes-casing", "line-opacity", ["case", ["==", ["get", "crew"], selectedCrew], 0.9, 0]);
      map.setPaintProperty("stops-planned", "circle-opacity", ["case", ["==", ["get", "crew"], selectedCrew], 1, 0.25]);
      map.setPaintProperty("stops-planned", "circle-stroke-opacity", ["case", ["==", ["get", "crew"], selectedCrew], 1, 0.25]);
    } else {
      map.setPaintProperty("routes", "line-opacity", 0.9);
      map.setPaintProperty("routes", "line-width", 2.5);
      map.setPaintProperty("routes-casing", "line-opacity", 0.7);
      map.setPaintProperty("stops-planned", "circle-opacity", 1);
      map.setPaintProperty("stops-planned", "circle-stroke-opacity", 1);
    }
  }, [ready, selectedCrew]);

  // voice markers (HTML, pulsing)
  useEffect(() => {
    const map = mapRef.current;
    const ml = libRef.current;
    if (!ready || !map || !ml) return;
    const keep = new Set(voice.map((v) => v.id));
    markers.current.forEach((m, id) => {
      if (!keep.has(id)) {
        m.remove();
        markers.current.delete(id);
      }
    });
    for (const v of voice) {
      const existing = markers.current.get(v.id);
      if (existing) {
        existing.setLngLat([v.lon, v.lat]);
        continue;
      }
      const node = document.createElement("div");
      node.className = "cs-voice";
      node.setAttribute("aria-label", `Voice report ${v.id}`);
      const dot = document.createElement("span");
      dot.className = "cs-voice-dot";
      const lbl = document.createElement("span");
      lbl.className = "cs-voice-label";
      lbl.textContent = v.id;
      node.append(dot, lbl);
      node.title = `${v.id}${v.crew ? ` → ${v.crew}` : ""}${v.reason ? `: ${v.reason}` : ""}`;
      node.addEventListener("click", () => v.crew && onSelectRef.current?.(v.crew));
      markers.current.set(v.id, new ml.Marker({ element: node }).setLngLat([v.lon, v.lat]).addTo(map));
    }
  }, [ready, voice]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !focus) return;
    map.flyTo({ center: [focus.lon, focus.lat], zoom: Math.max(map.getZoom(), 12), duration: 1200 });
  }, [ready, focus]);

  return (
    <div className="relative h-full w-full bg-[#0b0c0e]">
      {/* inline style: maplibre-gl.css sets .maplibregl-map { position: relative }, which would override a class */}
      <div ref={el} style={{ position: "absolute", inset: 0 }} role="region" aria-label={ariaLabel} />
      {!ready && !failed && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center text-sm text-zinc-500">Loading map…</div>
      )}
      {failed && (
        <div className="absolute inset-x-4 top-4 rounded-md border border-amber-500/30 bg-amber-950/60 px-3 py-2 text-sm text-amber-200">
          Map unavailable: {failed}
        </div>
      )}
    </div>
  );
}
