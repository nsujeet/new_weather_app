/**
 * SiteMap — Leaflet map: site marker + NOAA station circles + 30mi radius
 */
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
  noaaStations?: NoaaStation[];
  ashraStations?: AshraStation[];
  selectedStation?: string | null;
  onSelectStation?: (id: string) => void;
}

export default function SiteMap({
  siteLat, siteLon,
  noaaStations = [],
  selectedStation,
  onSelectStation,
}: Props) {
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
          pathOptions={{ color: "#3b82f6", fillOpacity: 0.04, weight: 1, dashArray: "4 4" }}
        />

        {/* Site marker */}
        <Marker position={[siteLat, siteLon]}>
          <Popup>
            <strong>Site</strong><br />
            {siteLat.toFixed(5)}, {siteLon.toFixed(5)}
          </Popup>
        </Marker>

        {/* NOAA station circles */}
        {noaaStations.map((s) => {
          if (s.LATITUDE == null || s.LONGITUDE == null) return null;
          const isSelected = s.GHCN_ID === selectedStation;
          const color = STATUS_COLOR[s.recommendation_status ?? ""] ?? "#9ca3af";
          return (
            <CircleMarker
              key={s.GHCN_ID}
              center={[s.LATITUDE, s.LONGITUDE]}
              radius={isSelected ? 10 : 7}
              pathOptions={{
                color: isSelected ? "#1d4ed8" : color,
                fillColor: isSelected ? "#3b82f6" : color,
                fillOpacity: 0.8,
                weight: isSelected ? 2 : 1,
              }}
              eventHandlers={{
                click: () => onSelectStation?.(s.GHCN_ID),
              }}
            >
              <Popup>
                <strong>{s.NAME}</strong><br />
                {s.GHCN_ID}<br />
                {s.dist_miles?.toFixed(1)} mi · Δ{s.elev_delta_ft?.toFixed(0)} ft
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
      </MapContainer>
      <p className="text-xs text-gray-400 px-2 py-1">
        🔵 selected · 🟢 recommended · 🟡 acceptable · 🔴 poor · dashed = 30 mi radius
      </p>
    </div>
  );
}
