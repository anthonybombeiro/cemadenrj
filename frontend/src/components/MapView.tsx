"use client";

import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";
import "leaflet/dist/leaflet.css";

import { READING_TYPE_LABELS, STATION_TYPE_LABELS, Station } from "@/lib/api";

const RJ_CENTER: [number, number] = [-22.25, -42.6];

const COLOR_BY_SOURCE: Record<string, string> = {
  inmet: "#2563eb",
  cemaden_nacional: "#16a34a",
  alerta_rio: "#ea580c",
};

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  } catch {
    return iso;
  }
}

// Guardamos vento em m/s (SI) no banco; exibimos em km/h a pedido do usuário.
const WIND_READING_TYPES = new Set(["vento_ms", "vento_rajada_ms"]);

function formatReadingValue(readingType: string, value: number): number {
  const emKmh = WIND_READING_TYPES.has(readingType) ? value * 3.6 : value;
  return Math.round(emKmh * 10) / 10;
}

export default function MapView({ stations }: { stations: Station[] }) {
  return (
    <MapContainer center={RJ_CENTER} zoom={8} className="h-full w-full" scrollWheelZoom>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {stations.map((station) => (
        <CircleMarker
          key={`${station.source}-${station.id}`}
          center={[station.latitude, station.longitude]}
          radius={7}
          pathOptions={{
            color: COLOR_BY_SOURCE[station.source] ?? "#6b7280",
            fillColor: COLOR_BY_SOURCE[station.source] ?? "#6b7280",
            fillOpacity: 0.85,
            weight: 2,
          }}
        >
          <Popup>
            <div className="space-y-1 text-sm">
              <p className="font-semibold">{station.name}</p>
              <p className="text-gray-600">
                {station.municipality || "Município não informado"} ·{" "}
                {STATION_TYPE_LABELS[station.station_type] ?? station.station_type}
              </p>
              <p className="text-xs uppercase tracking-wide text-gray-400">
                Fonte: {station.source} · código {station.external_id}
              </p>
              {station.latest_readings.length > 0 ? (
                <ul className="mt-2 space-y-0.5">
                  {station.latest_readings.map((r) => (
                    <li key={r.reading_type}>
                      <span className="font-medium">
                        {READING_TYPE_LABELS[r.reading_type] ?? r.reading_type}:
                      </span>{" "}
                      {formatReadingValue(r.reading_type, r.value)}{" "}
                      <span className="text-gray-400">({formatTimestamp(r.timestamp)})</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-gray-400">Sem leituras recentes.</p>
              )}
            </div>
          </Popup>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
