/**
 * SiteMap — Leaflet map: site marker + NOAA station circles + 30mi radius
 */
import { useState } from "react";
import { MapContainer, TileLayer, Marker, CircleMarker, Circle, Popup } from "react-leaflet";
import L from "leaflet";
import type { NoaaStation, AshraStation } from "../api";

// Fix Leaflet default icon broken in Vite (use bundled assets, not CDN)
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon   from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl:       markerIcon,
  shadowUrl:     markerShadow,
});

const STATUS_COLOR: Record<string, string> = {
  green:  "#22c55e",
  yellow: "#eab308",
  red:    "#ef4444",
  "":     "#9ca3af",
};

const MILES_TO_METERS = 1609.34;

interface Props {
  siteLat: number;
  siteLon: number;
  siteElevFt?: number;
  noaaStations?: NoaaStation[];
  ashraStations?: AshraStation[];
  selectedStation?: string | null;
  onSelectStation?: (id: string) => void;
}

export default function SiteMap({
  siteLat, siteLon, siteElevFt,
  noaaStations = [],
  ashraStations = [],
  selectedStation,
  onSelectStation,
}: Props) {
  const [showNoaa,   setShowNoaa]   = useState(true);
  const [showAshrae, setShowAshrae] = useState(true);

  return (
    <div className="rounded-lg overflow-hidden border border-gray-200">
      <MapContainer
        center={[siteLat, siteLon]}
        zoom={9}
        style={{ height: 340, width: "100%" }}
        scrollWheelZoom={false}
      >
        <TileLayer
          url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
          attribution='Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, SRTM | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)'
          subdomains="abc"
          maxZoom={17}
        />

        {/* 30-mile radius ring */}
        <Circle
          center={[siteLat, siteLon]}
          radius={30 * MILES_TO_METERS}
          pathOptions={{ color: "#14b8a6", fillOpacity: 0.04, weight: 1.5, dashArray: "6 4" }}
        />

        {/* ASHRAE stations (rendered below NOAA so NOAA is on top) */}
        {showAshrae && ashraStations.map((s) => {
          if (s.lat == null || s.lon == null) return null;
          return (
            <CircleMarker
              key={s.wmo}
              center={[s.lat, s.lon]}
              radius={9}
              pathOptions={{
                color: "#fff",
                weight: 2,
                fillColor: "#f97316",
                fillOpacity: 0.9,
              }}
            >
              <Popup>
                <strong>{s.station}</strong><br />
                WMO {s.wmo}<br />
                {s.dist_miles?.toFixed(1)} mi away<br />
                Elevation: {s.elev_ft?.toFixed(0)} ft
                {siteElevFt != null && s.elev_ft != null && (
                  <> (Δ{Math.abs(s.elev_ft - siteElevFt).toFixed(0)} ft)</>
                )}
              </Popup>
            </CircleMarker>
          );
        })}

        {/* NOAA station circles */}
        {showNoaa && noaaStations.map((s) => {
          if (s.LATITUDE == null || s.LONGITUDE == null) return null;
          const isSelected = s.GHCN_ID === selectedStation;
          const fill = isSelected ? "#3b82f6" : (STATUS_COLOR[s.recommendation_status ?? ""] ?? "#9ca3af");
          return (
            <CircleMarker
              key={s.GHCN_ID}
              center={[s.LATITUDE, s.LONGITUDE]}
              radius={isSelected ? 11 : 8}
              pathOptions={{
                color: "#fff",
                weight: isSelected ? 2.5 : 1.5,
                fillColor: fill,
                fillOpacity: 0.95,
              }}
              eventHandlers={{
                click: () => onSelectStation?.(s.GHCN_ID),
              }}
            >
              <Popup>
                <strong>{s.NAME}</strong><br />
                {s.GHCN_ID}<br />
                {s.dist_miles?.toFixed(1)} mi away<br />
                Elevation: {s.elevation_ft?.toFixed(0)} ft
                {s.elev_delta_ft != null && <> (Δ{s.elev_delta_ft.toFixed(0)} ft from site)</>}
                {onSelectStation && (
                  <><br /><button
                    onClick={() => onSelectStation(s.GHCN_ID)}
                    style={{ marginTop: 4, cursor: "pointer", color: "#2563eb" }}
                  >Select this station</button></>
                )}
              </Popup>
            </CircleMarker>
          );
        })}

        {/* Site marker on top */}
        <Marker position={[siteLat, siteLon]}>
          <Popup>
            <strong>Site</strong><br />
            {siteLat.toFixed(5)}, {siteLon.toFixed(5)}<br />
            {siteElevFt != null && <>Elevation: {siteElevFt.toFixed(0)} ft</>}
          </Popup>
        </Marker>
      </MapContainer>
      <div className="flex items-center gap-3 px-2 py-1 flex-wrap">
        <button
          onClick={() => setShowNoaa((v) => !v)}
          className="flex items-center gap-1.5 text-xs px-2 py-0.5 rounded border transition-colors"
          style={{
            borderColor: showNoaa ? "#3b82f6" : "#4b5563",
            background:  showNoaa ? "#1e3a5f" : "transparent",
            color:       showNoaa ? "#93c5fd"  : "#6b7280",
          }}
        >
          <span style={{ width: 10, height: 10, borderRadius: "50%", background: showNoaa ? "#3b82f6" : "#4b5563", display: "inline-block" }} />
          NOAA
        </button>
        <button
          onClick={() => setShowAshrae((v) => !v)}
          className="flex items-center gap-1.5 text-xs px-2 py-0.5 rounded border transition-colors"
          style={{
            borderColor: showAshrae ? "#f97316" : "#4b5563",
            background:  showAshrae ? "#431407" : "transparent",
            color:       showAshrae ? "#fdba74"  : "#6b7280",
          }}
        >
          <span style={{ width: 10, height: 10, borderRadius: "50%", background: showAshrae ? "#f97316" : "#4b5563", display: "inline-block" }} />
          ASHRAE
        </button>
        <span className="text-xs text-gray-500">Select a NOAA station — ASHRAE for reference only.</span>
      </div>
    </div>
  );
}
