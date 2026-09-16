"use client";

import { useEffect, useMemo, useState } from "react";

import {
  normalizeMunicipioName,
  RISK_LEVEL_COLORS,
  RISK_LEVEL_LABELS,
  RiskAlert,
  RiskAlertTipo,
  RiskLevel,
} from "@/lib/api";
import { computeBBox, geometryToPath, GeoJsonFeatureCollection, makeProjector } from "@/lib/geo";

const VIEW_W = 640;
const VIEW_H = 560;
const NO_DATA_COLOR = "#e5e7eb";
const DIMMED_COLOR = "#f3f4f6";

let geoCache: GeoJsonFeatureCollection | null = null;

type Selecao = { tipo: "municipio" | "redec"; valor: string } | null;

export default function RiskChoroplethMap({
  tipo,
  redecAlerts,
  municipioAlerts,
  municipioRedecMap,
  compact = false,
}: {
  tipo: RiskAlertTipo;
  redecAlerts: RiskAlert[];
  municipioAlerts: RiskAlert[];
  municipioRedecMap: Record<string, string>;
  /** Sem título interno nem busca — usado na aba "Riscos", onde os 4 mapas
   * aparecem lado a lado com um título próprio por fora. */
  compact?: boolean;
}) {
  const [geo, setGeo] = useState<GeoJsonFeatureCollection | null>(geoCache);
  const [busca, setBusca] = useState("");
  const [selecao, setSelecao] = useState<Selecao>(null);

  useEffect(() => {
    if (geoCache) return;
    let cancelled = false;
    fetch("/rj_municipios.geojson")
      .then((r) => r.json())
      .then((data: GeoJsonFeatureCollection) => {
        geoCache = data;
        if (!cancelled) setGeo(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const project = useMemo(() => {
    if (!geo) return null;
    return makeProjector(computeBBox(geo), VIEW_W, VIEW_H, 12);
  }, [geo]);

  // Geológico/hidrológico têm risco por município direto da fonte;
  // meteorológico/incêndio só têm por REDEC — nesse caso, todo município
  // daquela REDEC herda a cor da REDEC (só existe granularidade maior).
  const temGranularidadeMunicipal = tipo === "geologico" || tipo === "hidrologico";

  const corPorMunicipioNorm = useMemo(() => {
    const mapa = new Map<string, RiskLevel>();
    if (temGranularidadeMunicipal) {
      for (const a of municipioAlerts) {
        mapa.set(normalizeMunicipioName(a.municipio), a.risco);
      }
    } else {
      const riscoPorRedec = new Map(redecAlerts.map((a) => [a.redec, a.risco]));
      for (const [nomeNorm, redec] of Object.entries(municipioRedecMap)) {
        const risco = riscoPorRedec.get(redec);
        if (risco) mapa.set(nomeNorm, risco);
      }
    }
    return mapa;
  }, [temGranularidadeMunicipal, municipioAlerts, redecAlerts, municipioRedecMap]);

  const redecsDisponiveis = useMemo(
    () => Array.from(new Set(redecAlerts.map((a) => a.redec))).sort((a, b) => a.localeCompare(b)),
    [redecAlerts],
  );

  const opcoesBusca = useMemo(() => {
    if (!geo) return [];
    const municipios = geo.features
      .map((f) => f.properties.nome)
      .sort((a, b) => a.localeCompare(b))
      .map((nome) => ({ tipo: "municipio" as const, valor: nome }));
    const redecs = redecsDisponiveis.map((redec) => ({ tipo: "redec" as const, valor: redec }));
    const termo = busca.trim().toLowerCase();
    const todas = [...redecs, ...municipios];
    if (!termo) return [];
    return todas.filter((o) => o.valor.toLowerCase().includes(termo)).slice(0, 12);
  }, [geo, redecsDisponiveis, busca]);

  if (!geo || !project) {
    return <div className="p-6 text-center text-sm text-gray-400">Carregando mapa…</div>;
  }

  const selecionar = (op: { tipo: "municipio" | "redec"; valor: string }) => {
    setSelecao(op);
    setBusca(op.valor);
  };

  const limparSelecao = () => {
    setSelecao(null);
    setBusca("");
  };

  return (
    <div className={compact ? "" : "mt-4"}>
      {!compact && <h3 className="mb-2 text-sm font-semibold text-gray-700">Mapa por município</h3>}

      {!compact && (
        <div className="relative mb-2 max-w-xs">
          <div className="flex gap-2">
            <input
              type="text"
              value={busca}
              onChange={(e) => {
                setBusca(e.target.value);
                if (selecao) setSelecao(null);
              }}
              placeholder="Buscar município ou regional…"
              className="w-full rounded border border-gray-300 px-2 py-1 text-xs"
            />
            {(selecao || busca) && (
              <button
                type="button"
                onClick={limparSelecao}
                className="shrink-0 rounded border border-gray-300 px-2 py-1 text-xs text-gray-500 hover:bg-gray-50"
              >
                Limpar
              </button>
            )}
          </div>
          {busca && !selecao && opcoesBusca.length > 0 && (
            <ul className="absolute z-10 mt-1 w-full max-h-56 overflow-auto rounded border border-gray-200 bg-white text-xs shadow-md">
              {opcoesBusca.map((op) => (
                <li key={`${op.tipo}-${op.valor}`}>
                  <button
                    type="button"
                    onClick={() => selecionar(op)}
                    className="flex w-full items-center justify-between px-2 py-1.5 text-left hover:bg-gray-50"
                  >
                    <span>{op.valor}</span>
                    <span className="text-[10px] uppercase text-gray-400">
                      {op.tipo === "redec" ? "Regional" : "Município"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className={compact ? "w-full rounded border border-gray-200 bg-white" : "w-full max-w-2xl rounded border border-gray-200 bg-white"}
        role="img"
        aria-label={`Mapa do Rio de Janeiro por município — ${tipo}`}
      >
        {geo.features.map((feature) => {
          const nomeNorm = feature.properties.nomeNormalizado;
          const risco = corPorMunicipioNorm.get(nomeNorm);

          let emDestaque = true;
          if (selecao?.tipo === "municipio") {
            emDestaque = feature.properties.nome === selecao.valor;
          } else if (selecao?.tipo === "redec") {
            emDestaque = municipioRedecMap[nomeNorm] === selecao.valor;
          }

          const fill = !emDestaque ? DIMMED_COLOR : risco ? RISK_LEVEL_COLORS[risco] : NO_DATA_COLOR;

          return (
            <path
              key={feature.properties.codarea}
              d={geometryToPath(feature.geometry, project)}
              fill={fill}
              stroke="#ffffff"
              strokeWidth={0.6}
            >
              <title>
                {feature.properties.nome}
                {risco ? ` — ${RISK_LEVEL_LABELS[risco]}` : " — sem dado"}
              </title>
            </path>
          );
        })}
      </svg>
    </div>
  );
}
