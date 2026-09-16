"use client";

import { useEffect, useMemo, useState } from "react";

import {
  fetchRiskAlerts,
  RISK_ALERT_TIPO_LABELS,
  RISK_LEVEL_COLORS,
  RISK_LEVEL_LABELS,
  RiskAlert,
  RiskAlertTipo,
  RiskLevel,
} from "@/lib/api";

const TIPOS: RiskAlertTipo[] = ["hidrologico", "geologico", "meteorologico", "incendio"];
const NIVEIS: RiskLevel[] = ["muito_baixo", "baixo", "moderado", "alto", "muito_alto"];

/** Preto ou branco conforme o fundo, pra manter o texto legível em qualquer
 * cor da escala (BAIXO é amarelo puro — texto branco fica ilegível nele). */
function textColorFor(bg: string): string {
  const r = parseInt(bg.slice(1, 3), 16);
  const g = parseInt(bg.slice(3, 5), 16);
  const b = parseInt(bg.slice(5, 7), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.6 ? "#1f2937" : "#ffffff";
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  } catch {
    return iso;
  }
}

function RedecGrid({ alerts }: { alerts: RiskAlert[] }) {
  const sorted = useMemo(
    () => [...alerts].sort((a, b) => NIVEIS.indexOf(b.risco) - NIVEIS.indexOf(a.risco) || a.redec.localeCompare(b.redec)),
    [alerts],
  );
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {sorted.map((a) => {
        const bg = RISK_LEVEL_COLORS[a.risco];
        return (
          <div key={a.id} className="rounded-lg border border-gray-200 p-3 shadow-sm" style={{ backgroundColor: bg }}>
            <div className="text-xs font-semibold uppercase tracking-wide" style={{ color: textColorFor(bg) }}>
              {a.redec}
            </div>
            <div className="mt-1 text-lg font-bold" style={{ color: textColorFor(bg) }}>
              {RISK_LEVEL_LABELS[a.risco]}
            </div>
            <div className="mt-1 text-[11px] opacity-80" style={{ color: textColorFor(bg) }}>
              Atualizado: {formatTimestamp(a.atualizado_em ?? a.criado_em)}
            </div>
          </div>
        );
      })}
      {sorted.length === 0 && (
        <div className="col-span-full p-6 text-center text-sm text-gray-400">Sem dados para essa camada ainda.</div>
      )}
    </div>
  );
}

function MunicipioTable({ alerts }: { alerts: RiskAlert[] }) {
  const [sortAsc, setSortAsc] = useState(false);
  const [filter, setFilter] = useState("");

  const sorted = useMemo(() => {
    const filtered = alerts.filter((a) => a.municipio.toLowerCase().includes(filter.toLowerCase()));
    filtered.sort((a, b) => {
      const cmp = NIVEIS.indexOf(a.risco) - NIVEIS.indexOf(b.risco) || a.municipio.localeCompare(b.municipio);
      return sortAsc ? cmp : -cmp;
    });
    return filtered;
  }, [alerts, filter, sortAsc]);

  return (
    <div className="mt-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">Por município ({alerts.length})</h3>
        <input
          type="text"
          placeholder="Filtrar município…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-xs"
        />
      </div>
      <div className="max-h-80 overflow-auto rounded border border-gray-200">
        <table className="min-w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-gray-100 text-left text-xs uppercase tracking-wide text-gray-600">
            <tr>
              <th className="whitespace-nowrap px-3 py-2">Município</th>
              <th className="whitespace-nowrap px-3 py-2">REDEC</th>
              <th
                className="cursor-pointer select-none whitespace-nowrap px-3 py-2"
                onClick={() => setSortAsc((v) => !v)}
              >
                Risco{sortAsc ? " ▲" : " ▼"}
              </th>
              <th className="whitespace-nowrap px-3 py-2">Responsável</th>
              <th className="whitespace-nowrap px-3 py-2">Atualizado em</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((a) => {
              const bg = RISK_LEVEL_COLORS[a.risco];
              return (
                <tr key={a.id} className="border-b border-gray-100">
                  <td className="whitespace-nowrap px-3 py-1.5 font-medium text-gray-900">{a.municipio}</td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-gray-600">{a.redec}</td>
                  <td className="whitespace-nowrap px-3 py-1.5">
                    <span
                      className="rounded px-2 py-0.5 text-xs font-semibold"
                      style={{ backgroundColor: bg, color: textColorFor(bg) }}
                    >
                      {RISK_LEVEL_LABELS[a.risco]}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-gray-500">{a.responsavel || "—"}</td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-gray-500">
                    {formatTimestamp(a.atualizado_em ?? a.criado_em)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {sorted.length === 0 && (
          <div className="p-6 text-center text-sm text-gray-400">Nenhum município encontrado.</div>
        )}
      </div>
    </div>
  );
}

export default function AlertsPanel() {
  const [tipo, setTipo] = useState<RiskAlertTipo>("geologico");
  const [redecAlerts, setRedecAlerts] = useState<RiskAlert[]>([]);
  const [municipioAlerts, setMunicipioAlerts] = useState<RiskAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const temGranularidadeMunicipal = tipo === "geologico";

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      fetchRiskAlerts(tipo, "redec"),
      temGranularidadeMunicipal ? fetchRiskAlerts(tipo, "municipio") : Promise.resolve([]),
    ])
      .then(([redec, municipio]) => {
        if (cancelled) return;
        setRedecAlerts(redec);
        setMunicipioAlerts(municipio);
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
  }, [tipo, temGranularidadeMunicipal]);

  return (
    <div className="h-full w-full overflow-auto bg-white p-4">
      <div className="mb-4 flex flex-wrap gap-2">
        {TIPOS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTipo(t)}
            className={`rounded-full px-3 py-1.5 text-sm font-medium ${
              tipo === t ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
          >
            {RISK_ALERT_TIPO_LABELS[t]}
          </button>
        ))}
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-gray-500">
        <span>Legenda (padrão Defesa Civil-RJ):</span>
        {NIVEIS.map((n) => (
          <span key={n} className="flex items-center gap-1">
            <span
              className="inline-block h-3 w-3 rounded-sm border border-black/10"
              style={{ backgroundColor: RISK_LEVEL_COLORS[n] }}
            />
            {RISK_LEVEL_LABELS[n]}
          </span>
        ))}
      </div>

      {error && (
        <div className="mb-3 rounded bg-red-50 p-2 text-xs text-red-600">
          Não foi possível carregar alertas ({error}).
        </div>
      )}

      {loading ? (
        <div className="p-6 text-center text-sm text-gray-400">Carregando alertas…</div>
      ) : (
        <>
          <h3 className="mb-2 text-sm font-semibold text-gray-700">Por REDEC (regional de Defesa Civil)</h3>
          <RedecGrid alerts={redecAlerts} />
          {temGranularidadeMunicipal && <MunicipioTable alerts={municipioAlerts} />}
        </>
      )}

      <p className="mt-4 border-t border-gray-100 pt-2 text-xs text-gray-400">
        Fonte: Defesa Civil-RJ (CEMADEN-RJ/SEDEC), via API de integração do painel oficial. Classificação de risco
        emitida pela própria Defesa Civil — este painel só espelha o dado, não substitui os canais oficiais de
        alerta.
      </p>
    </div>
  );
}
