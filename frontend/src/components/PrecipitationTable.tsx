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

function formatMm(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(Math.round(value * 10) / 10).toFixed(1)}`;
}

/** Uma coluna por janela de acumulado — mesmo espírito da tabela do
 * Alerta Rio (websempre.rio.rj.gov.br/estacoes/), pedido pelo usuário
 * pra ter mais granularidade que só 1h/24h/96h. Sem 5min/10min de
 * propósito: ver comentário em `StationViewSet.precipitacao` no backend
 * (nossa cadência real não sustenta essa precisão pra a maioria das
 * fontes). `key` bate exatamente com o campo de `PrecipitacaoStation`.
 */
const JANELAS: { key: keyof PrecipitacaoStation; label: string; titulo: string }[] = [
  { key: "chuva_agora_mm", label: "Agora", titulo: "Última leitura bruta (só fontes tipo balde)" },
  { key: "acumulado_30min_mm", label: "30min", titulo: "Acumulado nos últimos 30 minutos" },
  { key: "acumulado_hoje_mm", label: "Hoje", titulo: "Acumulado desde a meia-noite local" },
  { key: "acumulado_1h_mm", label: "1h", titulo: "Acumulado na última 1 hora" },
  { key: "acumulado_2h_mm", label: "2h", titulo: "Acumulado nas últimas 2 horas" },
  { key: "acumulado_3h_mm", label: "3h", titulo: "Acumulado nas últimas 3 horas" },
  { key: "acumulado_4h_mm", label: "4h", titulo: "Acumulado nas últimas 4 horas" },
  { key: "acumulado_6h_mm", label: "6h", titulo: "Acumulado nas últimas 6 horas" },
  { key: "acumulado_12h_mm", label: "12h", titulo: "Acumulado nas últimas 12 horas" },
  { key: "acumulado_24h_mm", label: "24h", titulo: "Acumulado nas últimas 24 horas" },
  { key: "acumulado_96h_mm", label: "96h", titulo: "Acumulado nas últimas 96 horas (4 dias)" },
  { key: "acumulado_mes_mm", label: "Mês", titulo: "Acumulado desde o dia 1 do mês corrente" },
  { key: "pico_mm", label: "Pico", titulo: "Maior leitura individual nas últimas 24h (equivalente ao \"TX-15\" do Alerta Rio)" },
];

const COLUNAS_TEXTO = new Set(["name", "municipality", "source", "updated"]);

export default function PrecipitationTable({
  stations,
  municipioRedecMap = {},
}: {
  stations: PrecipitacaoStation[];
  /** Município (normalizado) → REDEC — ver DataTable.tsx/page.tsx. */
  municipioRedecMap?: Record<string, string>;
}) {
  const [sortKey, setSortKey] = useState<string>("acumulado_hoje_mm");
  const [sortAsc, setSortAsc] = useState(false);
  const redecOf = (municipality: string) => municipioRedecMap[normalizeMunicipioName(municipality)] ?? "";

  const sorted = useMemo(() => {
    const copy = [...stations];
    copy.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "name") cmp = a.name.localeCompare(b.name);
      else if (sortKey === "municipality") cmp = a.municipality.localeCompare(b.municipality);
      else if (sortKey === "source") cmp = a.source.localeCompare(b.source);
      else if (sortKey === "updated") cmp = (a.updated_at ?? "").localeCompare(b.updated_at ?? "");
      else {
        // Coluna numérica de janela (Agora/30min/Hoje/1h/.../Pico) — quem
        // não tem valor pra essa janela vai sempre pro fim, não importa
        // a direção (mesma regra já usada em DataTable.tsx).
        const va = a[sortKey as keyof PrecipitacaoStation] as number | null;
        const vb = b[sortKey as keyof PrecipitacaoStation] as number | null;
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        cmp = va - vb;
      }
      return sortAsc ? cmp : -cmp;
    });
    return copy;
  }, [stations, sortKey, sortAsc]);

  const toggleSort = (key: string) => {
    if (key === sortKey) {
      setSortAsc((v) => !v);
    } else {
      setSortKey(key);
      // Texto começa A→Z; coluna numérica começa do maior pro menor
      // (mais útil operacionalmente: quem está chovendo mais primeiro).
      setSortAsc(COLUNAS_TEXTO.has(key));
    }
  };

  const arrow = (key: string) => (key === sortKey ? (sortAsc ? " ▲" : " ▼") : "");

  const exportar = () => {
    const headers = [
      "Estação",
      "Município",
      "REDEC",
      "Fonte",
      ...JANELAS.map((j) => `${j.label} (mm)`),
      "Atualizado em",
    ];
    const rows = sorted.map((s) => [
      s.name,
      s.municipality || "",
      redecOf(s.municipality),
      SOURCE_LABELS[s.source] ?? s.source,
      ...JANELAS.map((j) => (s[j.key] as number | null) ?? ""),
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
            <th className="w-28 cursor-pointer select-none px-3 py-2" onClick={() => toggleSort("name")}>
              Estação{arrow("name")}
            </th>
            <th className="w-24 cursor-pointer select-none px-3 py-2" onClick={() => toggleSort("municipality")}>
              Município{arrow("municipality")}
            </th>
            <th className="w-20 whitespace-nowrap px-3 py-2">REDEC</th>
            <th className="w-20 cursor-pointer select-none px-3 py-2" onClick={() => toggleSort("source")}>
              Fonte{arrow("source")}
            </th>
            {JANELAS.map((j) => (
              <th
                key={j.key}
                className="w-14 cursor-pointer select-none whitespace-nowrap px-2 py-2 text-right"
                onClick={() => toggleSort(j.key)}
                title={j.titulo}
              >
                {j.label}
                {arrow(j.key)}
              </th>
            ))}
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
            const corTexto = faixa1h?.text;
            return (
              <tr
                key={`${s.source}-${s.id}`}
                className="border-b border-gray-100"
                style={faixa1h ? { backgroundColor: faixa1h.bg } : undefined}
                title={faixa1h?.label}
              >
                <td className="break-words px-3 py-1.5 font-medium" style={{ color: corTexto ?? "#111827" }}>
                  {s.name}
                </td>
                <td className="break-words px-3 py-1.5" style={{ color: corTexto ?? "#4b5563" }}>
                  {s.municipality || "—"}
                </td>
                <td className="break-words px-3 py-1.5" style={{ color: corTexto ?? "#6b7280" }}>
                  {redecOf(s.municipality) || "—"}
                </td>
                <td
                  className="break-words px-3 py-1.5 font-semibold"
                  style={{ color: faixa1h ? faixa1h.text : (SOURCE_COLORS[s.source] ?? "#374151") }}
                  title={s.source}
                >
                  {SOURCE_LABELS[s.source] ?? s.source}
                </td>
                {JANELAS.map((j) =>
                  j.key === "acumulado_hoje_mm" ? (
                    <td key={j.key} className="whitespace-nowrap px-2 py-1.5 text-right font-medium" style={{ color: corTexto ?? "#111827" }}>
                      <span className="inline-flex items-center justify-end gap-1.5">
                        {nivel && (
                          <span
                            className="inline-block h-2.5 w-2.5 rounded-full"
                            style={{ backgroundColor: nivel.color }}
                            title={nivel.label}
                          />
                        )}
                        {formatMm(s[j.key] as number | null)}
                      </span>
                    </td>
                  ) : (
                    <td key={j.key} className="whitespace-nowrap px-2 py-1.5 text-right" style={{ color: corTexto ?? "#1f2937" }}>
                      {formatMm(s[j.key] as number | null)}
                    </td>
                  ),
                )}
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
        Todas as janelas (exceto &ldquo;Hoje&rdquo;) só ficam disponíveis para fontes que reportam chuva por
        intervalo (Alerta Rio, CEMADEN, INMET, INEA, ...). Fontes que reportam total corrido do dia (Wunderground,
        Plugfield) mostram apenas &ldquo;Hoje&rdquo;. Sem colunas de 5min/10min: nossa cadência real é de ~15min pra
        quase todas as fontes, uma janela menor não traria informação nova além de &ldquo;Agora&rdquo;. Clique em
        qualquer cabeçalho pra ordenar (crescente/decrescente).
      </div>
    </div>
  );
}
