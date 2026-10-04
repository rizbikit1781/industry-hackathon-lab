"use client";

import "leaflet/dist/leaflet.css";
import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";
import type { NeighbourhoodFlag } from "@/lib/data/flags";

const CALGARY_CENTER: [number, number] = [51.0447, -114.0719];

const HAIL_COLOR: Record<NeighbourhoodFlag["hail_track"], string> = {
  high: "#b91c1c",
  medium: "#d97706",
  low: "#059669",
};

interface FlagMapProps {
  rows: NeighbourhoodFlag[];
  /** Which computed flag decides whether a marker is highlighted as "flagged". */
  activeFlag: "flag_v1" | "flag_v2";
}

export default function FlagMap({ rows, activeFlag }: FlagMapProps) {
  return (
    <MapContainer
      center={CALGARY_CENTER}
      zoom={11}
      scrollWheelZoom
      className="h-full w-full"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {rows.map((row) => {
        const flagged = row[activeFlag];
        return (
          <CircleMarker
            key={row.community_name}
            center={[row.latitude, row.longitude]}
            radius={flagged ? 9 : 5}
            pathOptions={{
              color: flagged ? "#111827" : HAIL_COLOR[row.hail_track],
              weight: flagged ? 2 : 1,
              fillColor: HAIL_COLOR[row.hail_track],
              fillOpacity: flagged ? 0.9 : 0.45,
            }}
          >
            <Popup>
              <div className="text-sm">
                <p className="font-semibold">{row.community_name}</p>
                <p>Sector: {row.sector}</p>
                <p>Hail track: {row.hail_track}</p>
                <p className="mt-1 font-medium">
                  {flagged ? "Flagged" : "Not flagged"}
                </p>
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
