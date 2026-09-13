"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { fetchStations, STATION_TYPE_LABELS, Station } from "@/lib/api";

const MapView = dynamic(() => import("@/components/MapView"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center text-gray-400">Carregando mapa…</div>
  ),
});

export default function HomePage() {
  const [stations, setStations] = useState<Station[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [municipalityFilter, setMunicipalityFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchStations()
      .then((data) => {
        if (!cancelled) setStations(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Erro desconhecido");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const municipalities = useMemo(
    () => Array.from(new Set(stations.map((s) => s.municipality).filter(Boolean))).sort(),
    [stations],
  );

  const filteredStations = useMemo(
    () =>
      stations.filter(
        (s) =>
          (!municipalityFilter || s.municipality === municipalityFilter) &&
          (!typeFilter || s.station_type === typeFilter),
      ),
    [stations, municipalityFilter, typeFilter],
  );

  return (
    <div className="flex h-screen flex-col">
      <header className="border-b border-gray-200 bg-white px-4 py-3 shadow-sm">
        <h1 className="text-lg font-bold text-gray-900">Painel Meteorológico/Hidrológico — CEMADEN-RJ</h1>
        <p className="text-xs text-gray-500">
          Agregação de estações públicas (INMET, CEMADEN nacional, Alerta Rio/GeoRio) para apoio à decisão.{" "}
          <strong>Não substitui os canais oficiais de emissão de alerta da Defesa Civil.</strong>
        </p>
      </header>

      <div className="flex flex-1 flex-col overflow-hidden md:flex-row">
        <aside className="flex flex-wrap gap-3 border-b border-gray-200 bg-white p-3 md:w-64 md:flex-col md:border-b-0 md:border-r">
          <div className="flex-1 md:flex-none">
            <label className="block text-xs font-medium text-gray-500">Município</label>
            <select
              className="mt-1 w-full rounded border border-gray-300 p-1.5 text-sm"
              value={municipalityFilter}
              onChange={(e) => setMunicipalityFilter(e.target.value)}
            >
              <option value="">Todos</option>
              {municipalities.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>

          <div className="flex-1 md:flex-none">
            <label className="block text-xs font-medium text-gray-500">Tipo de estação</label>
            <select
              className="mt-1 w-full rounded border border-gray-300 p-1.5 text-sm"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
            >
              <option value="">Todos</option>
              {Object.entries(STATION_TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          <div className="w-full text-xs text-gray-500 md:mt-4">
            {loading ? "Carregando estações…" : `${filteredStations.length} de ${stations.length} estações`}
          </div>
          {error && (
            <div className="w-full rounded bg-red-50 p-2 text-xs text-red-600">
              Não foi possível carregar dados da API ({error}). Verifique se o backend está rodando.
            </div>
          )}
        </aside>

        <main className="relative flex-1">
          <MapView stations={filteredStations} />
        </main>
      </div>
    </div>
  );
}
