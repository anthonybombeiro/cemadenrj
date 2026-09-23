"use client";

import { useMemo, useState } from "react";

import {
  getChuva1hFaixa,
  getChuva24hNivel,
  getDelayStatus,
  normalizeMunicipioName,
  PrecipitacaoStation,
  SOURCE_COLORS,
  SOURCE_LABELS,
} from "@/lib/api";
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

export default function PrecipitationTable({
  stations,
  municipioRedecMap = {},
}: {
  stations: PrecipitacaoStation[];
  /** Município (normalizado) → REDEC — ver DataTable.tsx/page.tsx. */
  municipioRedecMap?: Record<string, string>;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("hoje");
  const [sortAsc, setSortAsc] = useState(false);
  const redecOf = (municipality: string) => municipioRedecMap[normalizeMunicipioName(municipality)] ?? "";

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
    const headers = [
      "Estação",
      "Município",
      "REDEC",
      "Fonte",
      "Agora (mm)",
      "Hoje (mm)",
      "1h (mm)",
      "24h (mm)",
      "96h (mm)",
      "Atualizado em",
    ];
    const rows = sorted.map((s) => [
      s.name,
      s.municipality || "",
      redecOf(s.municipality),
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
      <div className="flex flex-wrap items-center gap-3 border-b border-gray-100 px-3 py-1.5 text-[11px] text-gray-500">
        <span>Fundo da linha por chuva na última 1h (igual à legenda do CEMADEN-RJ):</span>
        {[
          { bg: "#BEBEBE", label: "Atrasada" },
          { bg: "#63B8FF", label: "Fraca (0.2–5mm/h)" },
          { bg: "#FFFF66", label: "Moderada (5.1–25mm/h)" },
          { bg: "#FFA600", label: "Forte (25.1–50mm/h)" },
          { bg: "#CC0000", label: "Muito Forte (>50mm/h)" },
        ].map((f) => (
          <span key={f.label} className="flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded-sm border border-black/10" style={{ backgroundColor: f.bg }} />
            {f.label}
          </span>
        ))}
      </div>
      <table className="min-w-full border-collapse text-sm table-fixed">
        <thead className="sticky top-[4.5rem] bg-gray-100 text-left text-xs uppercase tracking-wide text-gray-600">
          <tr>
            <th className="w-32 cursor-pointer select-none px-3 py-2" onClick={() => toggleSort("name")}>
              Estação{arrow("name")}
            </th>
            <th className="w-28 cursor-pointer select-none px-3 py-2" onClick={() => toggleSort("municipality")}>
              Município{arrow("municipality")}
            </th>
            <th className="w-24 whitespace-nowrap px-3 py-2">REDEC</th>
            <th className="w-24 cursor-pointer select-none px-3 py-2" onClick={() => toggleSort("source")}>
              Fonte{arrow("source")}
            </th>
            <th className="w-20 whitespace-nowrap px-3 py-2">Agora</th>
            <th className="w-20 cursor-pointer select-none px-3 py-2" onClick={() => toggleSort("hoje")}>
              Hoje{arrow("hoje")}
            </th>
            <th className="w-16 whitespace-nowrap px-3 py-2">1h</th>
            <th className="w-16 whitespace-nowrap px-3 py-2">24h</th>
            <th className="w-16 whitespace-nowrap px-3 py-2">96h</th>
            <th className="w-24 cursor-pointer select-none px-3 py-2" onClick={() => toggleSort("updated")}>
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
            // Fundo da linha inteira pela chuva na última 1h — mesma
            // legenda exata do portal de sirenes do CEMADEN-RJ (ver
            // getChuva1hFaixa). "Atrasada" usa o mesmo corte de >1h sem
            // atualizar que já usamos pra colorir a coluna "Atualizado em".
            const faixa1h = getChuva1hFaixa(s.acumulado_1h_mm, atraso.atrasado);
            return (
              <tr
                key={`${s.source}-${s.id}`}
                className="border-b border-gray-100"
                style={faixa1h ? { backgroundColor: faixa1h.bg } : undefined}
                title={faixa1h?.label}
              >
                <td
                  className="break-words px-3 py-1.5 font-medium"
                  style={{ color: faixa1h?.text ?? "#111827" }}
                >
                  {s.name}
                </td>
                <td className="break-words px-3 py-1.5" style={{ color: faixa1h?.text ?? "#4b5563" }}>
                  {s.municipality || "—"}
                </td>
                <td className="break-words px-3 py-1.5" style={{ color: faixa1h?.text ?? "#6b7280" }}>
                  {redecOf(s.municipality) || "—"}
                </td>
                <td
                  className="break-words px-3 py-1.5 font-semibold"
                  style={{ color: faixa1h ? faixa1h.text : (SOURCE_COLORS[s.source] ?? "#374151") }}
                  title={s.source}
                >
                  {SOURCE_LABELS[s.source] ?? s.source}
                </td>
                <td className="break-words px-3 py-1.5" style={{ color: faixa1h?.text ?? "#1f2937" }}>
                  {formatMm(s.chuva_agora_mm)}
                </td>
                <td className="break-words px-3 py-1.5 font-medium" style={{ color: faixa1h?.text ?? "#111827" }}>
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
                <td className="break-words px-3 py-1.5" style={{ color: faixa1h?.text ?? "#1f2937" }}>
                  {formatMm(s.acumulado_1h_mm)}
                </td>
                <td className="break-words px-3 py-1.5" style={{ color: faixa1h?.text ?? "#1f2937" }}>
                  {formatMm(s.acumulado_24h_mm)}
                </td>
                <td className="break-words px-3 py-1.5" style={{ color: faixa1h?.text ?? "#1f2937" }}>
                  {formatMm(s.acumulado_96h_mm)}
                </td>
                <td className="break-words px-3 py-1.5" style={{ color: faixa1h ? faixa1h.text : atraso.color }} title={atraso.label}>
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
