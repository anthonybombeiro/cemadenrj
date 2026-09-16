"use client";

import { useEffect, useState } from "react";

import {
  fetchRiskAlerts,
  normalizeMunicipioName,
  RISK_ALERT_TIPO_LABELS,
  RISK_LEVEL_COLORS,
  RISK_LEVEL_LABELS,
  RiskAlert,
  RiskAlertTipo,
  RiskLevel,
} from "@/lib/api";
import RiskChoroplethMap from "@/components/RiskChoroplethMap";

const TIPOS: RiskAlertTipo[] = ["hidrologico", "geologico", "meteorologico", "incendio"];
const NIVEIS: RiskLevel[] = ["muito_baixo", "baixo", "moderado", "alto", "muito_alto"];
const COM_GRANULARIDADE_MUNICIPAL: RiskAlertTipo[] = ["geologico", "hidrologico"];

type DadosPorTipo = {
  redec: RiskAlert[];
  municipio: RiskAlert[];
};

function Legenda() {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
      {NIVEIS.map((n) => (
        <span key={n} className="flex items-center gap-1">
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm border border-black/10"
            style={{ backgroundColor: RISK_LEVEL_COLORS[n] }}
          />
          {RISK_LEVEL_LABELS[n]}
        </span>
      ))}
    </div>
  );
}

export default function RiscosOverviewPanel() {
  const [dados, setDados] = useState<Record<RiskAlertTipo, DadosPorTipo>>({
    hidrologico: { redec: [], municipio: [] },
    geologico: { redec: [], municipio: [] },
    meteorologico: { redec: [], municipio: [] },
    incendio: { redec: [], municipio: [] },
  });
  const [municipioRedecMap, setMunicipioRedecMap] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all(
      TIPOS.map((tipo) =>
        Promise.all([
          fetchRiskAlerts(tipo, "redec"),
          COM_GRANULARIDADE_MUNICIPAL.includes(tipo) ? fetchRiskAlerts(tipo, "municipio") : Promise.resolve([]),
        ]).then(([redec, municipio]) => [tipo, { redec, municipio }] as const),
      ),
    )
      .then((entradas) => {
        if (cancelled) return;
        const proximo = Object.fromEntries(entradas) as Record<RiskAlertTipo, DadosPorTipo>;
        setDados(proximo);
        const mapa: Record<string, string> = {};
        for (const a of proximo.geologico.municipio) mapa[normalizeMunicipioName(a.municipio)] = a.redec;
        setMunicipioRedecMap(mapa);
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

  return (
    <div className="h-full w-full overflow-auto bg-white p-4">
      <h2 className="mb-1 text-base font-semibold text-gray-900">Riscos — visão geral</h2>
      <p className="mb-4 text-xs text-gray-500">
        As 4 camadas de alerta da Defesa Civil-RJ lado a lado, cada uma com sua legenda.
      </p>

      {error && (
        <div className="mb-3 rounded bg-red-50 p-2 text-xs text-red-600">
          Não foi possível carregar alertas ({error}).
        </div>
      )}

      {loading ? (
        <div className="p-6 text-center text-sm text-gray-400">Carregando mapas…</div>
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {TIPOS.map((tipo) => (
            <div key={tipo} className="rounded-lg border border-gray-200 p-3">
              <h3 className="mb-1 text-sm font-semibold text-gray-800">{RISK_ALERT_TIPO_LABELS[tipo]}</h3>
              <Legenda />
              <RiskChoroplethMap
                tipo={tipo}
                redecAlerts={dados[tipo].redec}
                municipioAlerts={dados[tipo].municipio}
                municipioRedecMap={municipioRedecMap}
                compact
              />
            </div>
          ))}
        </div>
      )}

      <p className="mt-4 border-t border-gray-100 pt-2 text-xs text-gray-400">
        Fonte: Defesa Civil-RJ (CEMADEN-RJ/SEDEC), via API de integração do painel oficial. Classificação de risco
        emitida pela própria Defesa Civil — este painel só espelha o dado, não substitui os canais oficiais de
        alerta.
      </p>
    </div>
  );
}
