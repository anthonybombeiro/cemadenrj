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

export const READING_TYPE_LABELS: Record<string, string> = {
  chuva_mm: "Chuva acumulada (mm)",
  nivel_m: "Nível do rio (m)",
  temperatura_c: "Temperatura (°C)",
  umidade_pct: "Umidade relativa (%)",
  vento_ms: "Vento (m/s)",
  vento_rajada_ms: "Rajada de vento (m/s)",
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
