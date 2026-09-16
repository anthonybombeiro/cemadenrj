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
    <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] leading-tight text-gray-500 landscape:text-[9px]">
      {NIVEIS.map((n) => (
        <span key={n} className="flex items-center gap-1">
          <span
            className="inline-block h-2 w-2 shrink-0 rounded-sm border border-black/10"
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
    // Meta: em paisagem (PC, TV, tablet deitado) as 4 câmaras cabem inteiras
    // na tela, sem rolar — por isso landscape:overflow-hidden e o grid vira
    // flex-1 com 2 linhas fixas. Em retrato (celular, tablet em pé) mantém
    // sempre 2 colunas (nunca cai pra 1), pra pelo menos 2 mapas ficarem
    // visíveis juntos mesmo que o par de baixo precise de rolagem.
    <div className="flex h-full w-full flex-col overflow-y-auto bg-white p-3 landscape:overflow-hidden landscape:p-2">
      <h2 className="text-sm font-semibold text-gray-900 landscape:hidden">Riscos — visão geral</h2>
      <p className="mb-2 text-xs text-gray-500 landscape:hidden">
        As 4 camadas de alerta da Defesa Civil-RJ lado a lado, cada uma com sua legenda.
      </p>

      {error && (
        <div className="mb-2 shrink-0 rounded bg-red-50 p-2 text-xs text-red-600">
          Não foi possível carregar alertas ({error}).
        </div>
      )}

      {loading ? (
        <div className="p-6 text-center text-sm text-gray-400">Carregando mapas…</div>
      ) : (
        <div className="grid grid-cols-2 gap-2 landscape:min-h-0 landscape:flex-1 landscape:grid-rows-2">
          {TIPOS.map((tipo) => (
            <div
              key={tipo}
              className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-gray-200 p-1.5 landscape:p-1"
            >
              <h3 className="shrink-0 truncate text-[11px] font-semibold text-gray-800 landscape:text-[10px]">
                {RISK_ALERT_TIPO_LABELS[tipo]}
              </h3>
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

      <p className="mt-2 shrink-0 border-t border-gray-100 pt-1 text-[10px] text-gray-400 landscape:hidden">
        Fonte: Defesa Civil-RJ (CEMADEN-RJ/SEDEC), via API de integração do painel oficial. Classificação de risco
        emitida pela própria Defesa Civil — este painel só espelha o dado, não substitui os canais oficiais de
        alerta.
      </p>
    </div>
  );
}
