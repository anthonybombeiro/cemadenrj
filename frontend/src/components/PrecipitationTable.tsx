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

/** Uma coluna por janela de acumulado — pedido explícito do usuário
 * (2026-09-23), na mesma ordem, comparando com o Alerta Rio
 * (websempre.rio.rj.gov.br/estacoes/) e o portal de sirenes do
 * CEMADEN-RJ. "h"/"min" no lugar de "Horas"/"Minutos" por extenso
 * (pedido: "o horas pode ser resumido pelo h apenas no texto"). `key`
 * bate exatamente com o campo de `PrecipitacaoStation`. */
const JANELAS: { key: keyof PrecipitacaoStation; label: string; titulo: string }[] = [
  { key: "chuva_agora_mm", label: "Agora", titulo: "Última leitura bruta" },
  { key: "acumulado_5min_mm", label: "5min", titulo: "Acumulado nos últimos 5 minutos" },
  { key: "acumulado_10min_mm", label: "10min", titulo: "Acumulado nos últimos 10 minutos" },
  { key: "acumulado_15min_mm", label: "15min", titulo: "Acumulado nos últimos 15 minutos" },
  { key: "acumulado_30min_mm", label: "30min", titulo: "Acumulado nos últimos 30 minutos" },
  { key: "acumulado_hoje_mm", label: "Hoje", titulo: "Acumulado desde a meia-noite local" },
  { key: "acumulado_1h_mm", label: "1h", titulo: "Acumulado na última 1 hora" },
  { key: "acumulado_2h_mm", label: "2h", titulo: "Acumulado nas últimas 2 horas" },
  { key: "acumulado_3h_mm", label: "3h", titulo: "Acumulado nas últimas 3 horas" },
  { key: "acumulado_4h_mm", label: "4h", titulo: "Acumulado nas últimas 4 horas" },
  { key: "acumulado_6h_mm", label: "6h", titulo: "Acumulado nas últimas 6 horas" },
  { key: "acumulado_12h_mm", label: "12h", titulo: "Acumulado nas últimas 12 horas" },
  { key: "acumulado_24h_mm", label: "24h", titulo: "Acumulado nas últimas 24 horas" },
  { key: "acumulado_36h_mm", label: "36h", titulo: "Acumulado nas últimas 36 horas" },
  { key: "acumulado_48h_mm", label: "48h", titulo: "Acumulado nas últimas 48 horas" },
  { key: "acumulado_72h_mm", label: "72h", titulo: "Acumulado nas últimas 72 horas" },
  { key: "acumulado_96h_mm", label: "96h", titulo: "Acumulado nas últimas 96 horas" },
  { key: "acumulado_168h_mm", label: "168h", titulo: "Acumulado nas últimas 168 horas (7 dias)" },
  { key: "acumulado_1mes_mm", label: "1 Mês", titulo: "Acumulado nos últimos 30 dias corridos" },
  { key: "acumulado_mes_mm", label: "No Mês", titulo: "Acumulado desde o dia 1 do mês corrente" },
  { key: "pico_mm", label: "Pico", titulo: "Maior leitura individual nas últimas 24h (equivalente ao \"TX-15\" do Alerta Rio)" },
];

const COLUNAS_TEXTO = new Set(["name", "municipality", "redec", "source", "updated"]);

// Larguras das 3 colunas fixas (sticky) à esquerda — Redec/Município/
// Estação continuam visíveis rolando horizontalmente pelas ~20 colunas
// de dados (essencial em celular: sem isso, some o contexto de qual
// linha é qual assim que rola a tabela). Valores em px pra poder somar
// e calcular o `left` de cada uma.
const W_REDEC = 76;
const W_MUNICIPIO = 92;
const W_ESTACAO = 112;
const W_JANELA = 44;
const W_FONTE = 80;
const W_ATUALIZADO = 96;

export default function PrecipitationTable({
  stations,
  municipioRedecMap = {},
}: {
  stations: PrecipitacaoStation[];
  /** Município (normalizado) → REDEC — ver DataTable.tsx/page.tsx. */
  municipioRedecMap?: Record<string, string>;
}) {
  // Pedido do usuário: por padrão, ordenar pelos MAIORES valores de 15min
  // (é o que mais importa pra decisão operacional imediata) — o usuário
  // troca depois clicando em qualquer outro cabeçalho.
  const [sortKey, setSortKey] = useState<string>("acumulado_15min_mm");
  const [sortAsc, setSortAsc] = useState(false);
  const redecOf = (municipality: string) => municipioRedecMap[normalizeMunicipioName(municipality)] ?? "";

  const sorted = useMemo(() => {
    const copy = [...stations];
    copy.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "name") cmp = a.name.localeCompare(b.name);
      else if (sortKey === "municipality") cmp = a.municipality.localeCompare(b.municipality);
      else if (sortKey === "redec") cmp = redecOf(a.municipality).localeCompare(redecOf(b.municipality));
      else if (sortKey === "source") cmp = a.source.localeCompare(b.source);
      else if (sortKey === "updated") cmp = (a.updated_at ?? "").localeCompare(b.updated_at ?? "");
      else {
        // Coluna numérica de janela — quem não tem valor pra essa janela
        // vai sempre pro fim, não importa a direção.
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
  }, [stations, sortKey, sortAsc, municipioRedecMap]);

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
      "REDEC",
      "Município",
      "Estação",
      ...JANELAS.map((j) => `${j.label} (mm)`),
      "Fonte",
      "Atualizado em",
    ];
    const rows = sorted.map((s) => [
      redecOf(s.municipality),
      s.municipality || "",
      s.name,
      ...JANELAS.map((j) => (s[j.key] as number | null) ?? ""),
      SOURCE_LABELS[s.source] ?? s.source,
      formatTimestamp(s.updated_at),
    ]);
    downloadCsv(`cemaden-rj-precipitacao-${new Date().toISOString().slice(0, 10)}.csv`, headers, rows);
  };

  return (
    <div className="h-full w-full overflow-auto bg-white">
      <div className="sticky top-0 z-40 flex justify-end border-b border-gray-100 bg-white px-3 py-1.5">
        <button
          onClick={exportar}
          className="rounded border border-gray-300 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
          title="Exportar a tabela (com o filtro e a ordenação atuais) em CSV"
        >
          ⬇ Exportar CSV
        </button>
      </div>
      <div className="sticky top-9 z-40 flex flex-wrap items-center gap-2 border-b border-gray-100 bg-white px-3 py-1.5 text-[10px] text-gray-500 sm:text-[11px]">
        <span>Fundo da linha por chuva na última 1h:</span>
        {[
          { bg: "#BEBEBE", label: "Atrasada" },
          { bg: "#63B8FF", label: "Fraca" },
          { bg: "#FFFF66", label: "Moderada" },
          { bg: "#FFA600", label: "Forte" },
          { bg: "#CC0000", label: "Muito Forte" },
        ].map((f) => (
          <span key={f.label} className="flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded-sm border border-black/10" style={{ backgroundColor: f.bg }} />
            {f.label}
          </span>
        ))}
      </div>
      <table className="border-collapse text-xs sm:text-sm" style={{ tableLayout: "fixed" }}>
        <colgroup>
          <col style={{ width: W_REDEC }} />
          <col style={{ width: W_MUNICIPIO }} />
          <col style={{ width: W_ESTACAO }} />
          {JANELAS.map((j) => (
            <col key={j.key} style={{ width: W_JANELA }} />
          ))}
          <col style={{ width: W_FONTE }} />
          <col style={{ width: W_ATUALIZADO }} />
        </colgroup>
        <thead className="text-left uppercase tracking-wide text-gray-600">
          <tr>
            <th
              className="sticky top-[4.5rem] z-30 cursor-pointer select-none overflow-hidden text-ellipsis whitespace-nowrap bg-gray-100 px-2 py-2"
              style={{ left: 0, width: W_REDEC, maxWidth: W_REDEC, minWidth: W_REDEC }}
              onClick={() => toggleSort("redec")}
            >
              REDEC{arrow("redec")}
            </th>
            <th
              className="sticky top-[4.5rem] z-30 cursor-pointer select-none overflow-hidden text-ellipsis whitespace-nowrap bg-gray-100 px-2 py-2"
              style={{ left: W_REDEC, width: W_MUNICIPIO, maxWidth: W_MUNICIPIO, minWidth: W_MUNICIPIO }}
              onClick={() => toggleSort("municipality")}
            >
              Município{arrow("municipality")}
            </th>
            <th
              className="sticky top-[4.5rem] z-30 cursor-pointer select-none overflow-hidden text-ellipsis whitespace-nowrap bg-gray-100 px-2 py-2 shadow-[2px_0_3px_-1px_rgba(0,0,0,0.15)]"
              style={{ left: W_REDEC + W_MUNICIPIO, width: W_ESTACAO, maxWidth: W_ESTACAO, minWidth: W_ESTACAO }}
              onClick={() => toggleSort("name")}
            >
              Estação{arrow("name")}
            </th>
            {JANELAS.map((j) => (
              <th
                key={j.key}
                className="sticky top-[4.5rem] z-20 cursor-pointer select-none overflow-hidden whitespace-nowrap bg-gray-100 px-1 py-2 text-right"
                style={{ width: W_JANELA, maxWidth: W_JANELA, minWidth: W_JANELA }}
                onClick={() => toggleSort(j.key)}
                title={j.titulo}
              >
                {j.label}
                {arrow(j.key)}
              </th>
            ))}
            <th
              className="sticky top-[4.5rem] z-20 cursor-pointer select-none overflow-hidden text-ellipsis whitespace-nowrap bg-gray-100 px-2 py-2"
              style={{ width: W_FONTE, maxWidth: W_FONTE, minWidth: W_FONTE }}
              onClick={() => toggleSort("source")}
            >
              Fonte{arrow("source")}
            </th>
            <th
              className="sticky top-[4.5rem] z-20 cursor-pointer select-none whitespace-nowrap bg-gray-100 px-2 py-2"
              style={{ width: W_ATUALIZADO, maxWidth: W_ATUALIZADO, minWidth: W_ATUALIZADO }}
              onClick={() => toggleSort("updated")}
            >
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
            const bgFundo = faixa1h?.bg ?? "#ffffff";
            const corTexto = faixa1h?.text;
            return (
              <tr key={`${s.source}-${s.id}`} className="border-b border-gray-100" title={faixa1h?.label}>
                <td
                  className="sticky overflow-hidden text-ellipsis whitespace-nowrap px-2 py-1"
                  style={{
                    left: 0,
                    width: W_REDEC,
                    maxWidth: W_REDEC,
                    minWidth: W_REDEC,
                    backgroundColor: bgFundo,
                    color: corTexto ?? "#6b7280",
                  }}
                >
                  {redecOf(s.municipality) || "—"}
                </td>
                <td
                  className="sticky overflow-hidden text-ellipsis whitespace-nowrap px-2 py-1"
                  style={{
                    left: W_REDEC,
                    width: W_MUNICIPIO,
                    maxWidth: W_MUNICIPIO,
                    minWidth: W_MUNICIPIO,
                    backgroundColor: bgFundo,
                    color: corTexto ?? "#4b5563",
                  }}
                >
                  {s.municipality || "—"}
                </td>
                <td
                  className="sticky overflow-hidden text-ellipsis whitespace-nowrap px-2 py-1 font-medium shadow-[2px_0_3px_-1px_rgba(0,0,0,0.15)]"
                  style={{
                    left: W_REDEC + W_MUNICIPIO,
                    width: W_ESTACAO,
                    maxWidth: W_ESTACAO,
                    minWidth: W_ESTACAO,
                    backgroundColor: bgFundo,
                    color: corTexto ?? "#111827",
                  }}
                  title={s.name}
                >
                  {s.name}
                </td>
                {JANELAS.map((j) =>
                  j.key === "acumulado_hoje_mm" ? (
                    <td
                      key={j.key}
                      className="whitespace-nowrap px-1.5 py-1 text-right font-medium"
                      style={{ backgroundColor: bgFundo, color: corTexto ?? "#111827" }}
                    >
                      <span className="inline-flex items-center justify-end gap-1">
                        {nivel && (
                          <span
                            className="inline-block h-2 w-2 rounded-full"
                            style={{ backgroundColor: nivel.color }}
                            title={nivel.label}
                          />
                        )}
                        {formatMm(s[j.key] as number | null)}
                      </span>
                    </td>
                  ) : (
                    <td
                      key={j.key}
                      className="whitespace-nowrap px-1.5 py-1 text-right"
                      style={{ backgroundColor: bgFundo, color: corTexto ?? "#1f2937" }}
                    >
                      {formatMm(s[j.key] as number | null)}
                    </td>
                  ),
                )}
                <td
                  className="whitespace-nowrap px-2 py-1 font-semibold"
                  style={{ backgroundColor: bgFundo, color: faixa1h ? faixa1h.text : (SOURCE_COLORS[s.source] ?? "#374151") }}
                  title={s.source}
                >
                  {SOURCE_LABELS[s.source] ?? s.source}
                </td>
                <td
                  className="whitespace-nowrap px-2 py-1"
                  style={{ backgroundColor: bgFundo, color: faixa1h ? faixa1h.text : atraso.color }}
                  title={atraso.label}
                >
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
        &ldquo;1 Mês&rdquo; é janela CORRIDA de 30 dias; &ldquo;No Mês&rdquo; é desde o dia 1 do mês corrente
        (calendário) — são coisas diferentes. Colunas de janela menor que a cadência real de uma fonte (ex: uma
        fonte que só atualiza de hora em hora) saem iguais a &ldquo;Agora&rdquo;, não é erro. REDEC/Município/Estação
        ficam fixas rolando a tabela pro lado — em celular, arraste a tabela horizontalmente pra ver todas as
        janelas. Clique em qualquer cabeçalho pra ordenar.
      </div>
    </div>
  );
}
