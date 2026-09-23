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

/** Um "evento" ativo do nosso próprio AlertRule/AlertEvent (diferente do
 * RiskAlert, que é a classificação já pronta da Defesa Civil) — hoje
 * usado só pelas sirenes de alarme (ver ingestion/connectors/
 * cemaden_rj_sirenes.py): um AlertEvent sem resolved_at = sirene tocando
 * agora naquela estação. */
export type AlertEvent = {
  id: number;
  rule_name: string;
  severity: string;
  station: number;
  station_name: string;
  value: number;
  triggered_at: string;
  resolved_at: string | null;
};

export async function fetchActiveAlertEvents(): Promise<AlertEvent[]> {
  return fetchAllPages<AlertEvent>("/alerts/?active=true&limit=300");
}

type Paginated<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

async function getJson<T>(pathOuUrlAbsoluta: string): Promise<T> {
  // `next`/`previous` da paginação do DRF já vêm como URL absoluta —
  // aceitar os dois formatos evita ter que recortar API_BASE_URL de volta.
  const url = /^https?:\/\//.test(pathOuUrlAbsoluta) ? pathOuUrlAbsoluta : `${API_BASE_URL}${pathOuUrlAbsoluta}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Falha ao buscar ${pathOuUrlAbsoluta}: HTTP ${res.status}`);
  }
  return res.json();
}

/** Segue `next` até esgotar, em vez de pedir tudo com um `?limit=` gigante
 * numa passada só — o backend tem um teto de segurança no `limit`
 * (`api/pagination.py`, `max_limit=300`) justamente porque um payload
 * gigante numa única resposta já derrubou o processo CGI de produção (ver
 * commit que corrigiu o N+1 de `/api/stations/` em 2026-09-23). Conforme o
 * número de estações for crescendo, isso continua funcionando — só faz
 * mais uma volta de rede. */
async function fetchAllPages<T>(path: string): Promise<T[]> {
  const todos: T[] = [];
  let proximo: string | null = path;
  while (proximo) {
    const data: Paginated<T> | T[] = await getJson<Paginated<T> | T[]>(proximo);
    if (Array.isArray(data)) return data; // endpoint não-paginado — devolve direto
    todos.push(...data.results);
    proximo = data.next;
  }
  return todos;
}

export async function fetchStations(): Promise<Station[]> {
  return fetchAllPages<Station>("/stations/?limit=300");
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
  sirene: "Sirene/Alarme",
  outro: "Outro",
};

export const SOURCE_LABELS: Record<string, string> = {
  inmet: "INMET",
  cemaden_nacional: "CEMADEN Nacional",
  alerta_rio: "Alerta Rio/GeoRio",
  wunderground: "Wunderground",
  plugfield: "Plugfield",
  rio_chuva_bairro: "Chuva por Bairro (Rio)",
  cemaden_rj: "CEMADEN-RJ (rede própria)",
  cemaden_mctic: "CEMADEN Nacional/MCTIC",
  niteroi: "Niterói (Defesa Civil)",
  cemaden_rj_sirenes: "CEMADEN-RJ — Sirenes/Alarme",
  inea: "INEA — Alerta de Cheias",
};

/** Uma cor fixa por fonte, pra dar pra distinguir de relance numa tabela
 * cheia de linhas (mesma ideia da coluna "Rede" colorida da Rede Salvar do
 * CEMADEN nacional — ver docs/referencia-visual-rede-salvar.md). Onde a
 * fonte é literalmente a mesma rede que existe lá (INMET, CEMADEN-RJ,
 * CEMADEN nacional), reaproveitamos a cor exata deles; pras fontes que só
 * existem no nosso painel, pegamos emprestado uma cor do resto da paleta
 * deles (SIMEPAR/INEA/PCJ/SJC/CODESAL) que sobrou sem uso aqui — mantém a
 * mesma "família visual" sem inventar do zero. */
export const SOURCE_COLORS: Record<string, string> = {
  inmet: "#817C13", // = INMET na Rede Salvar
  cemaden_rj: "#720066", // = CEMADEN-RJ na Rede Salvar
  cemaden_mctic: "#0047F6", // = CEMADEN (nacional) na Rede Salvar
  cemaden_nacional: "#6c757d", // conector antigo/morto — cinza neutro
  alerta_rio: "#A91D3A", // emprestado da cor do CODESAL (Salvador) lá
  wunderground: "#FF6500", // emprestado da cor do SJC lá
  plugfield: "#033600", // emprestado da cor da ANA lá (INEA foi liberado pra fonte real abaixo)
  rio_chuva_bairro: "#543C18", // conector morto (503) — emprestado do PCJ
  niteroi: "#F712D4", // emprestado da cor do SIMEPAR lá
  inea: "#007261", // = INEA na Rede Salvar — cor real, não emprestada (agora existe de verdade)
  // Vermelho vivo (mesmo tom do "muito alto" em getChuva24hNivel) — não
  // reaproveitado da Rede Salvar dessa vez, de propósito: aqui o vermelho
  // já é usado consistentemente no resto do painel pra "emergência/perigo".
  cemaden_rj_sirenes: "#dc2626",
};

/** Faixas de atraso (tempo desde a última leitura) e cor associada — mesma
 * ideia da coluna "Data" da Rede Salvar, mas com limiares adaptados: as
 * fontes de lá misturam redes hidrológicas de cadência bem mais lenta
 * (horas), enquanto as nossas atualizam tipicamente a cada 15min–1h. */
export function getDelayStatus(iso: string | null): { color: string; label: string; atrasado: boolean } {
  if (!iso) return { color: "#9ca3af", label: "sem leitura", atrasado: true };
  const horas = (Date.now() - new Date(iso).getTime()) / 3_600_000;
  if (horas < 1) return { color: "#111827", label: "em dia", atrasado: false };
  if (horas < 6) return { color: "#b45309", label: "atenção (1h–6h sem atualizar)", atrasado: true };
  if (horas < 24) return { color: "#c2410c", label: "atrasado (6h–24h sem atualizar)", atrasado: true };
  return { color: "#991b1b", label: "muito atrasado (> 24h sem atualizar)", atrasado: true };
}

/** Faixas de chuva acumulada em 24h — os mesmos 3 cortes (10/30/70mm) usados
 * pelo próprio CEMADEN nacional na Rede Salvar (ícone amarelo/laranja/
 * vermelho), reaproveitados aqui em vez de inventar limiar próprio. */
export function getChuva24hNivel(mm: number | null): { color: string; label: string } | null {
  if (mm == null) return null;
  if (mm >= 70) return { color: "#dc2626", label: "> 70mm em 24h" };
  if (mm >= 30) return { color: "#f97316", label: "30–70mm em 24h" };
  if (mm >= 10) return { color: "#eab308", label: "10–30mm em 24h" };
  return null;
}

/** Cor de FUNDO DA LINHA pela chuva na última 1 hora — exatamente a mesma
 * legenda/cores do portal de sirenes do CEMADEN-RJ
 * (ConsultaPluviometros?cmd=dadosPluviometros&redec=Todos&municipio=Todos),
 * lida direto do HTML deles: "Atrasada"=#BEBEBE,
 * "Fraca" 0.2–5mm/h=#63B8FF, "Moderada" 5.1–25mm/h=#FFFF66,
 * "Forte" 25.1–50mm/h=#FFA600, "Muito Forte" >50mm/h=#CC0000. Sem chuva
 * significativa (< 0.2mm/h) e sem atraso: sem cor (fundo branco normal,
 * igual o comportamento deles). */
export function getChuva1hFaixa(
  mm: number | null,
  atrasado: boolean,
): { bg: string; text: string; label: string } | null {
  if (atrasado) return { bg: "#BEBEBE", text: "#1f2937", label: "Atrasada" };
  if (mm == null) return null;
  if (mm > 50) return { bg: "#CC0000", text: "#ffffff", label: "Muito Forte (acima de 50mm/h)" };
  if (mm >= 25.1) return { bg: "#FFA600", text: "#1f2937", label: "Forte (entre 25.1mm e 50mm/h)" };
  if (mm >= 5.1) return { bg: "#FFFF66", text: "#1f2937", label: "Moderada (entre 5.1mm e 25mm/h)" };
  if (mm >= 0.2) return { bg: "#63B8FF", text: "#1f2937", label: "Fraca (entre 0.2mm e 5mm/h)" };
  return null;
}

/** As 11 REDECs (Regionais de Defesa Civil) do estado do RJ — mesma lista
 * usada no backend (ingestion/connectors/cemaden_rj_alertas.py). */
export const REDECS = [
  "BAIXADA FLUMINENSE",
  "BAIXADA LITORÂNEA",
  "CAPITAL",
  "COSTA VERDE",
  "METROPOLITANA",
  "NORTE",
  "NOROESTE",
  "SERRANA I",
  "SERRANA II",
  "SUL I",
  "SUL II",
] as const;

/** Município → REDEC, montado a partir do endpoint de risco geológico por
 * município (o único que sempre traz os 92 municípios — ver AlertsPanel).
 * Usado pra agregar/filtrar as tabelas de Precipitação e Dados
 * Meteorológicos por REDEC, que hoje só existe nos alertas. */
export async function fetchMunicipioRedecMap(): Promise<Record<string, string>> {
  const data = await fetchRiskAlerts("geologico", "municipio");
  const mapa: Record<string, string> = {};
  for (const a of data) mapa[normalizeMunicipioName(a.municipio)] = a.redec;
  return mapa;
}
