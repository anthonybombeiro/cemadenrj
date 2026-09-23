"use client";

import { useMemo, useState } from "react";

import { getChuva24hNivel, getDelayStatus, PrecipitacaoStation, SOURCE_COLORS, SOURCE_LABELS } from "@/lib/api";
import { downloadCsv } from "@/lib/csvExport";

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  } catch {
    return iso;
  }
}

function formatMm(value: number | null): string {
  if (value === null) return "—";
  return `${(Math.round(value * 10) / 10).toFixed(1)} mm`;
}

type SortKey = "name" | "municipality" | "source" | "hoje" | "updated";

export default function PrecipitationTable({ stations }: { stations: PrecipitacaoStation[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("hoje");
  const [sortAsc, setSortAsc] = useState(false);

  const sorted = useMemo(() => {
    const copy = [...stations];
    copy.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "name") cmp = a.name.localeCompare(b.name);
      else if (sortKey === "municipality") cmp = a.municipality.localeCompare(b.municipality);
      else if (sortKey === "source") cmp = a.source.localeCompare(b.source);
      else if (sortKey === "hoje") cmp = (a.acumulado_hoje_mm ?? -1) - (b.acumulado_hoje_mm ?? -1);
      else if (sortKey === "updated") cmp = (a.updated_at ?? "").localeCompare(b.updated_at ?? "");
      return sortAsc ? cmp : -cmp;
    });
    return copy;
  }, [stations, sortKey, sortAsc]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortAsc((v) => !v);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  const arrow = (key: SortKey) => (key === sortKey ? (sortAsc ? " ▲" : " ▼") : "");

  const exportar = () => {
    const headers = ["Estação", "Município", "Fonte", "Agora (mm)", "Hoje (mm)", "1h (mm)", "24h (mm)", "96h (mm)", "Atualizado em"];
    const rows = sorted.map((s) => [
      s.name,
      s.municipality || "",
      SOURCE_LABELS[s.source] ?? s.source,
      s.chuva_agora_mm ?? "",
      s.acumulado_hoje_mm ?? "",
      s.acumulado_1h_mm ?? "",
      s.acumulado_24h_mm ?? "",
      s.acumulado_96h_mm ?? "",
      formatTimestamp(s.updated_at),
    ]);
    downloadCsv(`cemaden-rj-precipitacao-${new Date().toISOString().slice(0, 10)}.csv`, headers, rows);
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
      <table className="min-w-full border-collapse text-sm">
        <thead className="sticky top-9 bg-gray-100 text-left text-xs uppercase tracking-wide text-gray-600">
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
            <th className="whitespace-nowrap px-3 py-2">Agora</th>
            <th className="cursor-pointer select-none whitespace-nowrap px-3 py-2" onClick={() => toggleSort("hoje")}>
              Hoje{arrow("hoje")}
            </th>
            <th className="whitespace-nowrap px-3 py-2">1h</th>
            <th className="whitespace-nowrap px-3 py-2">24h</th>
            <th className="whitespace-nowrap px-3 py-2">96h</th>
            <th className="cursor-pointer select-none whitespace-nowrap px-3 py-2" onClick={() => toggleSort("updated")}>
              Atualizado em{arrow("updated")}
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((s) => {
            const atraso = getDelayStatus(s.updated_at);
            // Nível de chuva em 24h — se a fonte só tem "hoje" (total corrido
            // do dia, ver rodapé), usa esse como aproximação do nível.
            const nivel = getChuva24hNivel(s.acumulado_24h_mm ?? s.acumulado_hoje_mm);
            return (
              <tr key={`${s.source}-${s.id}`} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="whitespace-nowrap px-3 py-1.5 font-medium text-gray-900">{s.name}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-gray-600">{s.municipality || "—"}</td>
                <td
                  className="whitespace-nowrap px-3 py-1.5 font-semibold"
                  style={{ color: SOURCE_COLORS[s.source] ?? "#374151" }}
                  title={s.source}
                >
                  {SOURCE_LABELS[s.source] ?? s.source}
                </td>
                <td className="whitespace-nowrap px-3 py-1.5 text-gray-800">{formatMm(s.chuva_agora_mm)}</td>
                <td className="whitespace-nowrap px-3 py-1.5 font-medium text-gray-900">
                  <span className="inline-flex items-center gap-1.5">
                    {nivel && (
                      <span
                        className="inline-block h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: nivel.color }}
                        title={nivel.label}
                      />
                    )}
                    {formatMm(s.acumulado_hoje_mm)}
                  </span>
                </td>
                <td className="whitespace-nowrap px-3 py-1.5 text-gray-800">{formatMm(s.acumulado_1h_mm)}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-gray-800">{formatMm(s.acumulado_24h_mm)}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-gray-800">{formatMm(s.acumulado_96h_mm)}</td>
                <td className="whitespace-nowrap px-3 py-1.5" style={{ color: atraso.color }} title={atraso.label}>
                  {formatTimestamp(s.updated_at)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {sorted.length === 0 && (
        <div className="p-6 text-center text-sm text-gray-400">Nenhuma estação pluviométrica encontrada.</div>
      )}
      <div className="border-t border-gray-100 p-2 text-xs text-gray-400">
        &ldquo;1h&rdquo;/&ldquo;24h&rdquo;/&ldquo;96h&rdquo; só ficam disponíveis para fontes que reportam chuva por
        intervalo (Alerta Rio, CEMADEN, INMET). Fontes que reportam total corrido do dia (Wunderground, Plugfield)
        mostram apenas &ldquo;Hoje&rdquo;.
      </div>
    </div>
  );
}
