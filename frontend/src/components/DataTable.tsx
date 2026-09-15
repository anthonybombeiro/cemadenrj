"use client";

import { useMemo, useState } from "react";

import { READING_TYPE_LABELS, STATION_TYPE_LABELS, Station } from "@/lib/api";

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

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  } catch {
    return iso;
  }
}

function formatValue(value: number): string {
  return (Math.round(value * 100) / 100).toString();
}

type SortKey = "name" | "municipality" | "source" | "updated";

export default function DataTable({ stations }: { stations: Station[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("municipality");
  const [sortAsc, setSortAsc] = useState(true);

  const columns = useMemo(() => {
    const present = new Set<string>();
    stations.forEach((s) => s.latest_readings.forEach((r) => present.add(r.reading_type)));
    return COLUMN_ORDER.filter((c) => present.has(c));
  }, [stations]);

  const mostRecentUpdate = (s: Station): string | null => {
    if (s.latest_readings.length === 0) return null;
    return s.latest_readings.reduce((latest, r) => (r.timestamp > latest ? r.timestamp : latest), s.latest_readings[0].timestamp);
  };

  const sorted = useMemo(() => {
    const copy = [...stations];
    copy.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "name") cmp = a.name.localeCompare(b.name);
      else if (sortKey === "municipality") cmp = a.municipality.localeCompare(b.municipality);
      else if (sortKey === "source") cmp = a.source.localeCompare(b.source);
      else if (sortKey === "updated") {
        const ua = mostRecentUpdate(a) ?? "";
        const ub = mostRecentUpdate(b) ?? "";
        cmp = ua.localeCompare(ub);
      }
      return sortAsc ? cmp : -cmp;
    });
    return copy;
  }, [stations, sortKey, sortAsc]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortAsc((v) => !v);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  const arrow = (key: SortKey) => (key === sortKey ? (sortAsc ? " ▲" : " ▼") : "");

  return (
    <div className="h-full w-full overflow-auto bg-white">
      <table className="min-w-full border-collapse text-sm">
        <thead className="sticky top-0 bg-gray-100 text-left text-xs uppercase tracking-wide text-gray-600">
          <tr>
            <th className="cursor-pointer select-none whitespace-nowrap px-3 py-2" onClick={() => toggleSort("name")}>
              Estação{arrow("name")}
            </th>
            <th className="cursor-pointer select-none whitespace-nowrap px-3 py-2" onClick={() => toggleSort("municipality")}>
              Município{arrow("municipality")}
            </th>
            <th className="cursor-pointer select-none whitespace-nowrap px-3 py-2" onClick={() => toggleSort("source")}>
              Fonte{arrow("source")}
            </th>
            <th className="whitespace-nowrap px-3 py-2">Tipo</th>
            {columns.map((c) => (
              <th key={c} className="whitespace-nowrap px-3 py-2">
                {READING_TYPE_LABELS[c] ?? c}
              </th>
            ))}
            <th className="cursor-pointer select-none whitespace-nowrap px-3 py-2" onClick={() => toggleSort("updated")}>
              Atualizado em{arrow("updated")}
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((s) => {
            const readingsByType = Object.fromEntries(s.latest_readings.map((r) => [r.reading_type, r]));
            const updated = mostRecentUpdate(s);
            return (
              <tr key={`${s.source}-${s.id}`} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="whitespace-nowrap px-3 py-1.5 font-medium text-gray-900">{s.name}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-gray-600">{s.municipality || "—"}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-gray-600">{s.source}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-gray-600">
                  {STATION_TYPE_LABELS[s.station_type] ?? s.station_type}
                </td>
                {columns.map((c) => (
                  <td key={c} className="whitespace-nowrap px-3 py-1.5 text-gray-800">
                    {readingsByType[c] ? formatValue(readingsByType[c].value) : "—"}
                  </td>
                ))}
                <td className="whitespace-nowrap px-3 py-1.5 text-gray-500">
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
