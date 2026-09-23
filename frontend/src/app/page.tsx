"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import AlertsPanel from "@/components/AlertsPanel";
import DataTable, { METEOROLOGICAL_READING_TYPES } from "@/components/DataTable";
import PrecipitationTable from "@/components/PrecipitationTable";
import RiscosOverviewPanel from "@/components/RiscosOverviewPanel";
import {
  AlertEvent,
  fetchActiveAlertEvents,
  fetchMunicipioRedecMap,
  fetchPrecipitacao,
  fetchStations,
  normalizeMunicipioName,
  PrecipitacaoStation,
  REDECS,
  SOURCE_LABELS,
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

const VIEW_MODES: { key: ViewMode; label: string }[] = [
  { key: "mapa", label: "Mapa" },
  { key: "precipitacao", label: "Precipitação" },
  { key: "meteorologico", label: "Dados Meteorológicos" },
  { key: "alertas", label: "Alertas Ativos" },
  { key: "riscos", label: "Riscos" },
];

export default function HomePage() {
  const [stations, setStations] = useState<Station[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [municipalityFilter, setMunicipalityFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [redecFilter, setRedecFilter] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("mapa");

  // Município → REDEC — hoje só existia do lado dos alertas (AlertsPanel);
  // busca 1x aqui e reusa pra agregar/filtrar Precipitação e Dados
  // Meteorológicos por REDEC também (pedido do usuário).
  const [municipioRedecMap, setMunicipioRedecMap] = useState<Record<string, string>>({});
  useEffect(() => {
    let cancelled = false;
    fetchMunicipioRedecMap()
      .then((mapa) => {
        if (!cancelled) setMunicipioRedecMap(mapa);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const redecOf = (municipality: string): string =>
    municipioRedecMap[normalizeMunicipioName(municipality)] ?? "";

  const [precipitacao, setPrecipitacao] = useState<PrecipitacaoStation[]>([]);
  const [precipitacaoLoading, setPrecipitacaoLoading] = useState(false);
  const [precipitacaoError, setPrecipitacaoError] = useState<string | null>(null);
  const [precipitacaoLoaded, setPrecipitacaoLoaded] = useState(false);

  const [activeAlertEvents, setActiveAlertEvents] = useState<AlertEvent[]>([]);

  // Sirene tocando é dado de segurança em tempo real, não meteorológico
  // passivo — busca de novo sozinho a cada 1 minuto (bem mais frequente
  // que o resto do painel, que hoje só busca 1x ao carregar), em
  // qualquer aba, pra não depender do operador estar olhando o mapa no
  // momento exato do acionamento.
  useEffect(() => {
    let cancelled = false;
    const carregar = () => {
      fetchActiveAlertEvents()
        .then((data) => {
          if (!cancelled) setActiveAlertEvents(data);
        })
        .catch(() => {
          // Falha aqui não deve quebrar o resto do painel — só fica sem
          // o destaque de sirene até a próxima tentativa.
        });
    };
    carregar();
    const intervalo = setInterval(carregar, 60_000);
    return () => {
      cancelled = true;
      clearInterval(intervalo);
    };
  }, []);

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

  const sources = useMemo(
    () => Array.from(new Set(stations.map((s) => s.source).filter(Boolean))).sort(),
    [stations],
  );

  const filteredStations = useMemo(
    () =>
      stations.filter(
        (s) =>
          (!municipalityFilter || s.municipality === municipalityFilter) &&
          (!typeFilter || s.station_type === typeFilter) &&
          (!sourceFilter || s.source === sourceFilter) &&
          (!redecFilter || redecOf(s.municipality) === redecFilter),
      ),
    [stations, municipalityFilter, typeFilter, sourceFilter, redecFilter, municipioRedecMap],
  );

  const filteredPrecipitacao = useMemo(
    () =>
      precipitacao.filter(
        (s) =>
          (!municipalityFilter || s.municipality === municipalityFilter) &&
          (!typeFilter || s.station_type === typeFilter) &&
          (!sourceFilter || s.source === sourceFilter) &&
          (!redecFilter || redecOf(s.municipality) === redecFilter),
      ),
    [precipitacao, municipalityFilter, typeFilter, sourceFilter, redecFilter, municipioRedecMap],
  );

  const meteorologicalTypeSet = useMemo(() => new Set(METEOROLOGICAL_READING_TYPES), []);
  const meteorologicalStations = useMemo(
    () =>
      filteredStations.filter((s) => s.latest_readings.some((r) => meteorologicalTypeSet.has(r.reading_type))),
    [filteredStations, meteorologicalTypeSet],
  );

  return (
    <div className="flex h-screen flex-col">
      <header className="flex flex-col gap-3 border-b border-gray-200 bg-white px-4 py-3 shadow-sm">
        {activeAlertEvents.length > 0 && (
          <div className="animate-pulse rounded-lg bg-red-600 px-4 py-2 text-sm font-bold text-white shadow">
            🔊 {activeAlertEvents.length === 1 ? "1 sirene tocando agora" : `${activeAlertEvents.length} sirenes tocando agora`}
            : {activeAlertEvents.map((e) => e.station_name).join(", ")}
          </div>
        )}
        <div className="min-w-0">
          <h1 className="text-lg font-bold text-gray-900">Painel Meteorológico/Hidrológico — CEMADEN-RJ</h1>
          <p className="text-xs text-gray-500">
            Agregação de estações públicas (INMET, CEMADEN nacional, Alerta Rio/GeoRio, Wunderground, COR/Escritório
            de Dados Rio) para apoio à
            decisão. <strong>Não substitui os canais oficiais de emissão de alerta da Defesa Civil.</strong>
          </p>
        </div>
        {/* Pílulas com quebra de linha (igual à Alertas Ativos) em vez de uma
            fileira única de botões unidos — a fileira única não cabia em
            telas de celular e empurrava a página inteira para o lado. */}
        <div className="flex flex-wrap gap-2">
          {VIEW_MODES.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => setViewMode(key)}
              className={`rounded-full px-3 py-1.5 text-sm font-medium ${
                viewMode === key ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              }`}
            >
              {label}
            </button>
          ))}
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

            <div className="flex-1 md:flex-none">
              <label className="block text-xs font-medium text-gray-500">Fonte</label>
              <select
                className="mt-1 w-full rounded border border-gray-300 p-1.5 text-sm"
                value={sourceFilter}
                onChange={(e) => setSourceFilter(e.target.value)}
              >
                <option value="">Todas</option>
                {sources.map((s) => (
                  <option key={s} value={s}>
                    {SOURCE_LABELS[s] ?? s}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex-1 md:flex-none">
              <label className="block text-xs font-medium text-gray-500">REDEC</label>
              <select
                className="mt-1 w-full rounded border border-gray-300 p-1.5 text-sm"
                value={redecFilter}
                onChange={(e) => setRedecFilter(e.target.value)}
              >
                <option value="">Todas</option>
                {REDECS.map((r) => (
                  <option key={r} value={r}>
                    {r}
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
          {viewMode === "mapa" && <MapView stations={filteredStations} activeAlertEvents={activeAlertEvents} />}
          {viewMode === "precipitacao" && (
            <PrecipitationTable stations={filteredPrecipitacao} municipioRedecMap={municipioRedecMap} />
          )}
          {viewMode === "meteorologico" && (
            <DataTable
              stations={filteredStations}
              readingTypes={METEOROLOGICAL_READING_TYPES}
              defaultSortKey="temperatura_c"
              municipioRedecMap={municipioRedecMap}
            />
          )}
          {viewMode === "alertas" && <AlertsPanel />}
          {viewMode === "riscos" && <RiscosOverviewPanel />}
        </main>
      </div>
    </div>
  );
}
