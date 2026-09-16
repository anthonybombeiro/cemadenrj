"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import AlertsPanel from "@/components/AlertsPanel";
import DataTable, { METEOROLOGICAL_READING_TYPES } from "@/components/DataTable";
import PrecipitationTable from "@/components/PrecipitationTable";
import RiscosOverviewPanel from "@/components/RiscosOverviewPanel";
import {
  fetchPrecipitacao,
  fetchStations,
  PrecipitacaoStation,
  STATION_TYPE_LABELS,
  Station,
} from "@/lib/api";

const MapView = dynamic(() => import("@/components/MapView"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center text-gray-400">Carregando mapa…</div>
  ),
});

type ViewMode = "mapa" | "precipitacao" | "meteorologico" | "alertas" | "riscos";

export default function HomePage() {
  const [stations, setStations] = useState<Station[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [municipalityFilter, setMunicipalityFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("mapa");

  const [precipitacao, setPrecipitacao] = useState<PrecipitacaoStation[]>([]);
  const [precipitacaoLoading, setPrecipitacaoLoading] = useState(false);
  const [precipitacaoError, setPrecipitacaoError] = useState<string | null>(null);
  const [precipitacaoLoaded, setPrecipitacaoLoaded] = useState(false);

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

  // Busca sob demanda (só quando a aba é aberta pela 1ª vez) — o cálculo de
  // acumulados no backend varre até 96h de leituras, então evita fazer isso
  // toda vez que o painel carrega se o operador nunca abrir essa aba.
  useEffect(() => {
    if (viewMode !== "precipitacao" || precipitacaoLoaded) return;
    let cancelled = false;
    setPrecipitacaoLoading(true);
    fetchPrecipitacao()
      .then((data) => {
        if (!cancelled) {
          setPrecipitacao(data);
          setPrecipitacaoLoaded(true);
        }
      })
      .catch((err) => {
        if (!cancelled) setPrecipitacaoError(err instanceof Error ? err.message : "Erro desconhecido");
      })
      .finally(() => {
        if (!cancelled) setPrecipitacaoLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [viewMode, precipitacaoLoaded]);

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

  const filteredPrecipitacao = useMemo(
    () => precipitacao.filter((s) => !municipalityFilter || s.municipality === municipalityFilter),
    [precipitacao, municipalityFilter],
  );

  const meteorologicalTypeSet = useMemo(() => new Set(METEOROLOGICAL_READING_TYPES), []);
  const meteorologicalStations = useMemo(
    () =>
      filteredStations.filter((s) => s.latest_readings.some((r) => meteorologicalTypeSet.has(r.reading_type))),
    [filteredStations, meteorologicalTypeSet],
  );

  return (
    <div className="flex h-screen flex-col">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-gray-200 bg-white px-4 py-3 shadow-sm">
        <div>
          <h1 className="text-lg font-bold text-gray-900">Painel Meteorológico/Hidrológico — CEMADEN-RJ</h1>
          <p className="text-xs text-gray-500">
            Agregação de estações públicas (INMET, CEMADEN nacional, Alerta Rio/GeoRio, Wunderground, COR/Escritório
            de Dados Rio) para apoio à
            decisão. <strong>Não substitui os canais oficiais de emissão de alerta da Defesa Civil.</strong>
          </p>
        </div>
        <div className="flex shrink-0 overflow-hidden rounded border border-gray-300">
          <button
            type="button"
            onClick={() => setViewMode("mapa")}
            className={`px-3 py-1.5 text-sm font-medium ${
              viewMode === "mapa" ? "bg-blue-600 text-white" : "bg-white text-gray-600 hover:bg-gray-50"
            }`}
          >
            Mapa
          </button>
          <button
            type="button"
            onClick={() => setViewMode("precipitacao")}
            className={`border-l border-gray-300 px-3 py-1.5 text-sm font-medium ${
              viewMode === "precipitacao" ? "bg-blue-600 text-white" : "bg-white text-gray-600 hover:bg-gray-50"
            }`}
          >
            Precipitação
          </button>
          <button
            type="button"
            onClick={() => setViewMode("meteorologico")}
            className={`border-l border-gray-300 px-3 py-1.5 text-sm font-medium ${
              viewMode === "meteorologico" ? "bg-blue-600 text-white" : "bg-white text-gray-600 hover:bg-gray-50"
            }`}
          >
            Dados Meteorológicos
          </button>
          <button
            type="button"
            onClick={() => setViewMode("alertas")}
            className={`border-l border-gray-300 px-3 py-1.5 text-sm font-medium ${
              viewMode === "alertas" ? "bg-blue-600 text-white" : "bg-white text-gray-600 hover:bg-gray-50"
            }`}
          >
            Alertas Ativos
          </button>
          <button
            type="button"
            onClick={() => setViewMode("riscos")}
            className={`border-l border-gray-300 px-3 py-1.5 text-sm font-medium ${
              viewMode === "riscos" ? "bg-blue-600 text-white" : "bg-white text-gray-600 hover:bg-gray-50"
            }`}
          >
            Riscos
          </button>
        </div>
      </header>

      <div className="flex flex-1 flex-col overflow-hidden md:flex-row">
        {viewMode !== "alertas" && viewMode !== "riscos" && (
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
              {viewMode === "precipitacao"
                ? precipitacaoLoading
                  ? "Carregando precipitação…"
                  : `${filteredPrecipitacao.length} estações pluviométricas`
                : viewMode === "meteorologico"
                  ? loading
                    ? "Carregando estações…"
                    : `${meteorologicalStations.length} estações meteorológicas`
                  : loading
                    ? "Carregando estações…"
                    : `${filteredStations.length} de ${stations.length} estações`}
            </div>
            {error && (
              <div className="w-full rounded bg-red-50 p-2 text-xs text-red-600">
                Não foi possível carregar dados da API ({error}). Verifique se o backend está rodando.
              </div>
            )}
            {precipitacaoError && (
              <div className="w-full rounded bg-red-50 p-2 text-xs text-red-600">
                Não foi possível carregar precipitação ({precipitacaoError}).
              </div>
            )}
          </aside>
        )}

        <main className="relative flex-1 overflow-hidden">
          {viewMode === "mapa" && <MapView stations={filteredStations} />}
          {viewMode === "precipitacao" && <PrecipitationTable stations={filteredPrecipitacao} />}
          {viewMode === "meteorologico" && (
            <DataTable stations={filteredStations} readingTypes={METEOROLOGICAL_READING_TYPES} />
          )}
          {viewMode === "alertas" && <AlertsPanel />}
          {viewMode === "riscos" && <RiscosOverviewPanel />}
        </main>
      </div>
    </div>
  );
}
