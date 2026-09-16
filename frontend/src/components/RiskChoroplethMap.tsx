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

let geoCache: GeoJsonFeatureCollection | null = null;

export default function RiskChoroplethMap({
  tipo,
  redecAlerts,
  municipioAlerts,
  municipioRedecMap,
}: {
  tipo: RiskAlertTipo;
  redecAlerts: RiskAlert[];
  municipioAlerts: RiskAlert[];
  municipioRedecMap: Record<string, string>;
}) {
  const [geo, setGeo] = useState<GeoJsonFeatureCollection | null>(geoCache);

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

  if (!geo || !project) {
    return <div className="p-6 text-center text-sm text-gray-400">Carregando mapa…</div>;
  }

  return (
    <div className="mt-4">
      <h3 className="mb-2 text-sm font-semibold text-gray-700">Mapa por município</h3>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="w-full max-w-2xl rounded border border-gray-200 bg-white"
        role="img"
        aria-label={`Mapa do Rio de Janeiro por município — ${tipo}`}
      >
        {geo.features.map((feature) => {
          const nomeNorm = feature.properties.nomeNormalizado;
          const risco = corPorMunicipioNorm.get(nomeNorm);
          const fill = risco ? RISK_LEVEL_COLORS[risco] : NO_DATA_COLOR;
          return (
            <path key={feature.properties.codarea} d={geometryToPath(feature.geometry, project)} fill={fill} stroke="#ffffff" strokeWidth={0.6}>
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
