export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000/api";

export type LatestReading = {
  reading_type: string;
  value: number;
  timestamp: string;
};

export type Station = {
  id: number;
  source: string;
  external_id: string;
  name: string;
  municipality: string;
  station_type: string;
  status: string;
  latitude: number;
  longitude: number;
  altitude_m: number | null;
  latest_readings: LatestReading[];
};

export type Reading = {
  id: number;
  reading_type: string;
  value: number;
  timestamp: string;
};

type Paginated<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Falha ao buscar ${path}: HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchStations(): Promise<Station[]> {
  const data = await getJson<Paginated<Station> | Station[]>("/stations/?limit=1000");
  return Array.isArray(data) ? data : data.results;
}

export async function fetchStationReadings(stationId: number): Promise<Reading[]> {
  return getJson<Reading[]>(`/stations/${stationId}/readings/`);
}

export type PrecipitacaoStation = {
  id: number;
  source: string;
  station_type: string;
  external_id: string;
  name: string;
  municipality: string;
  latitude: number;
  longitude: number;
  updated_at: string | null;
  /** Última leitura "bruta" — só preenchido pra fontes tipo "balde" (Alerta Rio, INMET, ...). */
  chuva_agora_mm: number | null;
  /** Acumulado desde a meia-noite local. Sempre que disponível, pra qualquer fonte. */
  acumulado_hoje_mm: number | null;
  /** Só disponível pra fontes tipo "balde" — Wunderground/Plugfield reportam total corrido do dia, não dá pra somar em janelas menores sem contar errado. */
  acumulado_1h_mm: number | null;
  acumulado_24h_mm: number | null;
  acumulado_96h_mm: number | null;
};

export async function fetchPrecipitacao(): Promise<PrecipitacaoStation[]> {
  return getJson<PrecipitacaoStation[]>("/stations/precipitacao/");
}

export type RiskAlertTipo = "hidrologico" | "geologico" | "meteorologico" | "incendio";
export type RiskLevel = "muito_baixo" | "baixo" | "moderado" | "alto" | "muito_alto";

export type RiskAlert = {
  id: number;
  tipo: RiskAlertTipo;
  redec: string;
  municipio: string;
  risco: RiskLevel;
  numero_externo: string;
  responsavel: string;
  criado_em: string | null;
  atualizado_em: string | null;
  fonte: string;
};

/** Cores oficiais usadas pela própria Defesa Civil-RJ no painel de alertas
 * (achadas em `/integracao/envia/cemaden/`, seção "Legenda") — mantém aqui
 * pra qualquer operador que já conhece o painel legado reconhecer de cara. */
export const RISK_LEVEL_COLORS: Record<RiskLevel, string> = {
  muito_baixo: "#28a745",
  baixo: "#ffff19",
  moderado: "#ffc107",
  alto: "#bd2130",
  muito_alto: "#6f42c1",
};

export const RISK_LEVEL_LABELS: Record<RiskLevel, string> = {
  muito_baixo: "Muito baixo",
  baixo: "Baixo",
  moderado: "Moderado",
  alto: "Alto",
  muito_alto: "Muito alto",
};

export const RISK_ALERT_TIPO_LABELS: Record<RiskAlertTipo, string> = {
  hidrologico: "Aviso Hidrológico",
  geologico: "Aviso Geológico",
  meteorologico: "Severidade Meteorológica",
  incendio: "Risco de Incêndio Florestal",
};

export async function fetchRiskAlerts(
  tipo: RiskAlertTipo,
  escopo?: "redec" | "municipio",
): Promise<RiskAlert[]> {
  const params = new URLSearchParams({ tipo, limit: "200" });
  if (escopo) params.set("escopo", escopo);
  const data = await getJson<Paginated<RiskAlert> | RiskAlert[]>(`/risk-alerts/?${params}`);
  return Array.isArray(data) ? data : data.results;
}

/** Mesma normalização usada pra gerar `rj_municipios.geojson` (maiúsculas,
 * sem acento, espaços colapsados) — precisa bater dos dois lados pra casar
 * o nome que vem da Defesa Civil-RJ com o nome oficial do IBGE no polígono.
 * Só um nome diverge entre as duas fontes (achado comparando as 92 de cada
 * lado): "Armação de Búzios" (Defesa Civil) vs "Armação dos Búzios" (IBGE). */
export function normalizeMunicipioName(nome: string): string {
  const normalizado = nome
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toUpperCase()
    .replace(/\s+/g, " ")
    .trim();
  if (normalizado === "ARMACAO DE BUZIOS") return "ARMACAO DOS BUZIOS";
  return normalizado;
}

export const READING_TYPE_LABELS: Record<string, string> = {
  chuva_mm: "Chuva acumulada (mm)",
  nivel_m: "Nível do rio (m)",
  temperatura_c: "Temperatura (°C)",
  umidade_pct: "Umidade relativa (%)",
  // Chave continua "vento_ms" (é assim que o backend guarda, em m/s — SI
  // padrão) mas exibimos em km/h a pedido do usuário; a conversão fica em
  // DataTable.tsx/MapView.tsx, só na hora de formatar pra tela.
  vento_ms: "Vento (km/h)",
  vento_rajada_ms: "Rajada de vento (km/h)",
  vento_dir_graus: "Direção do vento (°)",
  mare_m: "Maré (m)",
};

export const STATION_TYPE_LABELS: Record<string, string> = {
  pluviometrica: "Pluviométrica",
  hidrologica: "Hidrológica",
  meteorologica: "Meteorológica",
  mare: "Maré/Oceanográfica",
  outro: "Outro",
};

export const SOURCE_LABELS: Record<string, string> = {
  inmet: "INMET",
  cemaden_nacional: "CEMADEN Nacional",
  alerta_rio: "Alerta Rio/GeoRio",
  wunderground: "Wunderground",
  plugfield: "Plugfield",
  rio_chuva_bairro: "Chuva por Bairro (Rio)",
};
