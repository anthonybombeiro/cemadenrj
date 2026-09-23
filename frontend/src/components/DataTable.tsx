"use client";

import { useMemo, useState } from "react";

import {
  getDelayStatus,
  normalizeMunicipioName,
  READING_TYPE_LABELS,
  SOURCE_COLORS,
  SOURCE_LABELS,
  STATION_TYPE_LABELS,
  Station,
} from "@/lib/api";
import { downloadCsv } from "@/lib/csvExport";

const COLUMN_ORDER = [
  "chuva_mm",
  "nivel_m",
  "temperatura_c",
  "umidade_pct",
  "vento_ms",
  "vento_rajada_ms",
  "vento_dir_graus",
  "mare_m",
];

/** Tipos de leitura que aparecem na tabela de Dados Meteorológicos — chuva
 * fica de fora porque tem tela própria (com acumulados), ver PrecipitationTable. */
export const METEOROLOGICAL_READING_TYPES = [
  "temperatura_c",
  "umidade_pct",
  "vento_ms",
  "vento_rajada_ms",
  "vento_dir_graus",
  "nivel_m",
  "mare_m",
];

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  } catch {
    return iso;
  }
}

// Guardamos vento em m/s (SI) no banco; exibimos em km/h a pedido do
// usuário. Conversão só de exibição — não afeta ordenação (transformação
// monotônica, a ordem relativa é a mesma nas duas unidades).
const WIND_READING_TYPES = new Set(["vento_ms", "vento_rajada_ms"]);

function formatReadingValue(readingType: string, value: number): string {
  const emKmh = WIND_READING_TYPES.has(readingType) ? value * 3.6 : value;
  return (Math.round(emKmh * 10) / 10).toString();
}

const FIXED_SORT_KEYS = new Set(["name", "municipality", "source", "updated"]);

export default function DataTable({
  stations,
  readingTypes,
  defaultSortKey = "municipality",
  municipioRedecMap = {},
}: {
  stations: Station[];
  /** Restringe colunas e estações exibidas a esses tipos de leitura (default: todos). */
  readingTypes?: string[];
  /** Coluna usada pra ordenar de cara — "name"/"municipality"/"source"/"updated"
   * ou um tipo de leitura (ex: "temperatura_c"). Colunas de valor começam
   * ordenadas do maior pro menor; as demais, A→Z. */
  defaultSortKey?: string;
  /** Município (normalizado) → REDEC — pra mostrar/exportar a coluna REDEC.
   * Sem isso a coluna fica em branco, não quebra nada (ver page.tsx). */
  municipioRedecMap?: Record<string, string>;
}) {
  const redecOf = (municipality: string) => municipioRedecMap[normalizeMunicipioName(municipality)] ?? "";
  const [sortKey, setSortKey] = useState<string>(defaultSortKey);
  const [sortAsc, setSortAsc] = useState(!FIXED_SORT_KEYS.has(defaultSortKey) ? false : true);

  const allowedTypes = useMemo(() => (readingTypes ? new Set(readingTypes) : null), [readingTypes]);

  const filteredStations = useMemo(() => {
    if (!allowedTypes) return stations;
    return stations.filter((s) => s.latest_readings.some((r) => allowedTypes.has(r.reading_type)));
  }, [stations, allowedTypes]);

  const columns = useMemo(() => {
    const present = new Set<string>();
    filteredStations.forEach((s) => s.latest_readings.forEach((r) => present.add(r.reading_type)));
    return COLUMN_ORDER.filter((c) => present.has(c) && (!allowedTypes || allowedTypes.has(c)));
  }, [filteredStations, allowedTypes]);

  const mostRecentUpdate = (s: Station): string | null => {
    if (s.latest_readings.length === 0) return null;
    return s.latest_readings.reduce((latest, r) => (r.timestamp > latest ? r.timestamp : latest), s.latest_readings[0].timestamp);
  };

  const sorted = useMemo(() => {
    const copy = [...filteredStations];
    copy.sort((a, b) => {
      if (sortKey === "name") return sortAsc ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
      if (sortKey === "municipality")
        return sortAsc ? a.municipality.localeCompare(b.municipality) : b.municipality.localeCompare(a.municipality);
      if (sortKey === "source") return sortAsc ? a.source.localeCompare(b.source) : b.source.localeCompare(a.source);
      if (sortKey === "updated") {
        const ua = mostRecentUpdate(a) ?? "";
        const ub = mostRecentUpdate(b) ?? "";
        return sortAsc ? ua.localeCompare(ub) : ub.localeCompare(ua);
      }
      // Coluna de valor (ex: temperatura_c) — quem não tem leitura desse
      // tipo vai sempre pro fim, não importa a direção.
      const va = a.latest_readings.find((r) => r.reading_type === sortKey)?.value;
      const vb = b.latest_readings.find((r) => r.reading_type === sortKey)?.value;
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return sortAsc ? va - vb : vb - va;
    });
    return copy;
  }, [filteredStations, sortKey, sortAsc]);

  const toggleSort = (key: string) => {
    if (key === sortKey) {
      setSortAsc((v) => !v);
    } else {
      setSortKey(key);
      setSortAsc(!FIXED_SORT_KEYS.has(key) ? false : true);
    }
  };

  const arrow = (key: string) => (key === sortKey ? (sortAsc ? " ▲" : " ▼") : "");

  const exportar = () => {
    const headers = [
      "Estação",
      "Município",
      "REDEC",
      "Fonte",
      "Tipo",
      ...columns.map((c) => READING_TYPE_LABELS[c] ?? c),
      "Atualizado em",
    ];
    const rows = sorted.map((s) => {
      const readingsByType = Object.fromEntries(s.latest_readings.map((r) => [r.reading_type, r]));
      const updated = mostRecentUpdate(s);
      return [
        s.name,
        s.municipality || "",
        redecOf(s.municipality),
        SOURCE_LABELS[s.source] ?? s.source,
        STATION_TYPE_LABELS[s.station_type] ?? s.station_type,
        ...columns.map((c) => (readingsByType[c] ? formatReadingValue(c, readingsByType[c].value) : "")),
        updated ? formatTimestamp(updated) : "",
      ];
    });
    downloadCsv(`cemaden-rj-estacoes-${new Date().toISOString().slice(0, 10)}.csv`, headers, rows);
  };

  return (
    <div className="h-full w-full overflow-auto bg-white">
      <div className="sticky top-0 z-10 flex justify-end border-b border-gray-100 bg-white px-3 py-1.5">
        <button
          onClick={exportar}
          className="rounded border border-gray-300 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
          title="Exportar a tabela (com o filtro e a ordenação atuais) em CSV"
        >
          ⬇ Exportar CSV
        </button>
      </div>
      <table className="min-w-full border-collapse text-sm table-fixed">
        <thead className="sticky top-9 bg-gray-100 text-left text-xs uppercase tracking-wide text-gray-600">
          <tr>
            <th
              className="w-32 cursor-pointer select-none px-3 py-2"
              onClick={() => toggleSort("name")}
            >
              Estação{arrow("name")}
            </th>
            <th
              className="w-28 cursor-pointer select-none px-3 py-2"
              onClick={() => toggleSort("municipality")}
            >
              Município{arrow("municipality")}
            </th>
            <th className="w-24 whitespace-nowrap px-3 py-2">REDEC</th>
            <th className="w-24 cursor-pointer select-none px-3 py-2" onClick={() => toggleSort("source")}>
              Fonte{arrow("source")}
            </th>
            <th className="w-24 whitespace-nowrap px-3 py-2">Tipo</th>
            {columns.map((c) => (
              <th
                key={c}
                className="w-20 cursor-pointer select-none px-3 py-2"
                onClick={() => toggleSort(c)}
              >
                {READING_TYPE_LABELS[c] ?? c}
                {arrow(c)}
              </th>
            ))}
            <th className="w-24 cursor-pointer select-none px-3 py-2" onClick={() => toggleSort("updated")}>
              Atualizado em{arrow("updated")}
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((s) => {
            const readingsByType = Object.fromEntries(s.latest_readings.map((r) => [r.reading_type, r]));
            const updated = mostRecentUpdate(s);
            const atraso = getDelayStatus(updated);
            return (
              <tr key={`${s.source}-${s.id}`} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="break-words px-3 py-1.5 font-medium text-gray-900">{s.name}</td>
                <td className="break-words px-3 py-1.5 text-gray-600">{s.municipality || "—"}</td>
                <td className="break-words px-3 py-1.5 text-gray-500">{redecOf(s.municipality) || "—"}</td>
                <td
                  className="break-words px-3 py-1.5 font-semibold"
                  style={{ color: SOURCE_COLORS[s.source] ?? "#374151" }}
                  title={s.source}
                >
                  {SOURCE_LABELS[s.source] ?? s.source}
                </td>
                <td className="break-words px-3 py-1.5 text-gray-600">
                  {STATION_TYPE_LABELS[s.station_type] ?? s.station_type}
                </td>
                {columns.map((c) => (
                  <td key={c} className="break-words px-3 py-1.5 text-gray-800">
                    {readingsByType[c] ? formatReadingValue(c, readingsByType[c].value) : "—"}
                  </td>
                ))}
                <td
                  className="break-words px-3 py-1.5"
                  style={{ color: atraso.color }}
                  title={atraso.label}
                >
                  {updated ? formatTimestamp(updated) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {sorted.length === 0 && (
        <div className="p-6 text-center text-sm text-gray-400">Nenhuma estação encontrada com os filtros atuais.</div>
      )}
    </div>
  );
}
