"""
Conector para estações pessoais (PWS) do Weather Underground / The Weather
Company (IBM) no estado do RJ.

Ao contrário de uma tentativa anterior (descartada) de descobrir a rede
inteira de estações por engenharia reversa, este conector só consulta
códigos de estação específicos e já conhecidos, vindos de fontes externas
confiáveis — Defesas Civis municipais (Rio das Ostras, Casimiro de Abreu,
Macaé) e uma planilha repassada por terceiros cobrindo mais municípios do
RJ (filtrada para manter só estações a até 40km do município de
referência). Essa é a forma pretendida de uso da API: consultar dados de
estações cujo ID você já tem, com uma chave de API própria (não a chave
pública embutida no site, usada só numa investigação inicial e
descartada).

Como conseguir a chave (self-service, gratuito, sem precisar negociar
com a IBM):
  1. Criar conta em https://www.wunderground.com/signup
  2. Em "My Profile" > "My Devices", adicionar um dispositivo PWS (não
     precisa ter uma estação de verdade, é só um passo burocrático)
  3. Gerar a chave em https://www.wunderground.com/member/api-keys
  4. Configurar em WUNDERGROUND_API_KEY no .env

Endpoint usado: GET https://api.weather.com/v2/pws/observations/current
(mesma API que a própria página do Wunderground usa, sem CAPTCHA nem
bloqueio para consultas de estações já conhecidas).
"""

from __future__ import annotations

import datetime as dt
import logging

import requests
from django.conf import settings

from core.models import Reading, Station

from .base import BaseConnector, bucket_from_running_daily

logger = logging.getLogger("ingestion")

CURRENT_URL = "https://api.weather.com/v2/pws/observations/current"

# Passadas pelas Defesas Civis municipais (setembro/2026). Nome/município
# confirmados consultando cada código nesta mesma API.
STATIONS_RJ = [
    {"external_id": "IRIODA6", "name": "Rio das Ostras", "municipality": "Rio das Ostras", "latitude": -22.527074, "longitude": -41.957646},
    {"external_id": "IRIODA15", "name": "REBIO União", "municipality": "Rio das Ostras", "latitude": -22.426845, "longitude": -42.020862},
    {"external_id": "IRIODA5", "name": "Rio das Ostras", "municipality": "Rio das Ostras", "latitude": -22.43, "longitude": -41.95},
    {"external_id": "IRIODA16", "name": "Rio das Ostras", "municipality": "Rio das Ostras", "latitude": -22.43, "longitude": -41.95},
    {"external_id": "ICASIM3", "name": "Casimiro de Abreu", "municipality": "Casimiro de Abreu", "latitude": -22.473088, "longitude": -42.201497},
    {"external_id": "ICASIM4", "name": "Casimiro de Abreu", "municipality": "Casimiro de Abreu", "latitude": -22.369534, "longitude": -42.208562},
    {"external_id": "ICASIM5", "name": "Barra de São João", "municipality": "Casimiro de Abreu", "latitude": -22.573707, "longitude": -41.985545},
    {"external_id": "IMACA53", "name": "Sana", "municipality": "Macaé", "latitude": -22.325677, "longitude": -42.186135},
    {"external_id": "INOVAF35", "name": "São Pedro Da Serra", "municipality": "Nova Friburgo", "latitude": -22.31715, "longitude": -42.323932},
    {"external_id": "INOVAF41", "name": "Lumiar", "municipality": "Nova Friburgo", "latitude": -22.404548, "longitude": -42.43402},
    {"external_id": "IARMAO4", "name": "Armação dos Búzios", "municipality": "Armação dos Búzios", "latitude": -22.75, "longitude": -41.88},
    {"external_id": "IARMAO9", "name": "Armação dos Búzios", "municipality": "Armação dos Búzios", "latitude": -22.75, "longitude": -41.88},
    {"external_id": "ICABOF7", "name": "Tamoios", "municipality": "Cabo Frio", "latitude": -22.732238, "longitude": -41.975914},
    {"external_id": "ICABOF8", "name": "Tamoios", "municipality": "Cabo Frio", "latitude": -22.717779, "longitude": -42.022813},
    {"external_id": "ICABOF4", "name": "Cabo Frio", "municipality": "Cabo Frio", "latitude": -22.884885, "longitude": -42.033956},
    {"external_id": "IARRAI26", "name": "Arraial do Cabo", "municipality": "Arraial do Cabo", "latitude": -22.964696, "longitude": -42.026695},
    # Lote adicional (setembro/2026) — lista repassada por terceiros (não
    # descoberta por varredura própria), filtrada para manter só estações a
    # até 40km do município consultado (campo "distance_km" da planilha
    # original), para não incluir estações de outros estados que só
    # apareceram por serem "a mais próxima" de um município de fronteira.
    {"external_id": "IANGRA31", "name": "Angra dos Reis", "municipality": "Angra dos Reis", "latitude": -23.012, "longitude": -44.298},
    {"external_id": "IANGRA34", "name": "Angra dos Reis", "municipality": "Angra dos Reis", "latitude": -22.99949, "longitude": -44.24549},
    {"external_id": "IAREAL7", "name": "Areal", "municipality": "Areal", "latitude": -22.22684, "longitude": -43.11701},
    {"external_id": "IARMAO3", "name": "Armação dos Búzios", "municipality": "Araruama", "latitude": -22.77118, "longitude": -41.92827},
    {"external_id": "IBARRA137", "name": "Barra do Piraí", "municipality": "Barra do Piraí", "latitude": -22.36619, "longitude": -43.86626},
    {"external_id": "IBARRA138", "name": "Barra do Piraí", "municipality": "Barra do Piraí", "latitude": -22.36581, "longitude": -43.86441},
    {"external_id": "IBARRA22", "name": "Barra do Piraí", "municipality": "Barra do Piraí", "latitude": -22.44419, "longitude": -43.78485},
    {"external_id": "IBARRA57", "name": "Barra do Piraí", "municipality": "Barra do Piraí", "latitude": -22.37011, "longitude": -43.86977},
    {"external_id": "IBARRA79", "name": "Barra do Piraí", "municipality": "Barra do Piraí", "latitude": -22.45505, "longitude": -43.85439},
    {"external_id": "IBARRA88", "name": "Barra do Piraí", "municipality": "Barra do Piraí", "latitude": -22.45842, "longitude": -43.84123},
    {"external_id": "IBARRADO2", "name": "Barra Do Piraí", "municipality": "Barra do Piraí", "latitude": -22.44515, "longitude": -43.78394},
    {"external_id": "IBOCAI22", "name": "Bocaina de Minas", "municipality": "Itatiaia", "latitude": -22.29651, "longitude": -44.52643},
    {"external_id": "ICUNHA2", "name": "Cunha", "municipality": "Paraty", "latitude": -23.10686, "longitude": -44.96511},
    {"external_id": "ICUNHA4", "name": "Cunha", "municipality": "Paraty", "latitude": -23.18708, "longitude": -44.93203},
    {"external_id": "ICUNHA6", "name": "Cunha", "municipality": "Paraty", "latitude": -23.07028, "longitude": -44.96467},
    {"external_id": "ICUNHA7", "name": "Cunha", "municipality": "Paraty", "latitude": -23.21659, "longitude": -45.0341},
    {"external_id": "ICUNHA8", "name": "Cunha", "municipality": "Paraty", "latitude": -23.12822, "longitude": -44.93477},
    {"external_id": "ICUNHA9", "name": "Cunha", "municipality": "Paraty", "latitude": -23.02299, "longitude": -45.02363},
    {"external_id": "IITAGU8", "name": "Itaguaí", "municipality": "Itaguaí", "latitude": -22.91842, "longitude": -43.84706},
    {"external_id": "IITATI13", "name": "Itatiaia", "municipality": "Itatiaia", "latitude": -22.42211, "longitude": -44.53963},
    {"external_id": "IITATI4", "name": "Itatiaia", "municipality": "Barra Mansa", "latitude": -22.45121, "longitude": -44.52211},
    {"external_id": "IJUIZD29", "name": "Juiz de Fora", "municipality": "Comendador Levy Gasparian", "latitude": -21.783, "longitude": -43.362},
    {"external_id": "IJUIZD31", "name": "Juiz de Fora", "municipality": "Comendador Levy Gasparian", "latitude": -21.78475, "longitude": -43.34854},
    {"external_id": "IJUIZD37", "name": "Juiz de Fora", "municipality": "Comendador Levy Gasparian", "latitude": -21.7828, "longitude": -43.37049},
    {"external_id": "IJUIZD39", "name": "Juiz de Fora", "municipality": "Comendador Levy Gasparian", "latitude": -21.7766, "longitude": -43.4108},
    {"external_id": "IJUIZD9", "name": "Juiz de Fora", "municipality": "Comendador Levy Gasparian", "latitude": -21.783, "longitude": -43.396},
    {"external_id": "IMACA15", "name": "Macaé", "municipality": "Macaé", "latitude": -22.40134, "longitude": -41.80165},
    {"external_id": "IMACA26", "name": "Macaé", "municipality": "Carapebus", "latitude": -22.3899, "longitude": -41.80611},
    {"external_id": "IMACA30", "name": "Macaé", "municipality": "Casimiro de Abreu", "latitude": -22.40429, "longitude": -41.86027},
    {"external_id": "IMACA31", "name": "Macaé", "municipality": "Carapebus", "latitude": -22.36832, "longitude": -41.78816},
    {"external_id": "IMACA32", "name": "Macaé", "municipality": "Carapebus", "latitude": -22.38228, "longitude": -41.78487},
    {"external_id": "IMACA44", "name": "Macaé", "municipality": "Carapebus", "latitude": -22.403, "longitude": -41.796},
    {"external_id": "IMACA46", "name": "Macaé", "municipality": "Carapebus", "latitude": -22.3888, "longitude": -41.77677},
    {"external_id": "IMACA51", "name": "Macaé", "municipality": "Carapebus", "latitude": -22.337, "longitude": -41.775},
    {"external_id": "IMACA52", "name": "Macaé", "municipality": "Carapebus", "latitude": -22.334, "longitude": -41.73642},
    {"external_id": "IMACA56", "name": "Macaé", "municipality": "Rio das Ostras", "latitude": -22.41, "longitude": -41.808},
    {"external_id": "IMACA58", "name": "Macaé", "municipality": "Carapebus", "latitude": -22.37008, "longitude": -41.77558},
    {"external_id": "IMACA6", "name": "Macaé", "municipality": "Macaé", "latitude": -22.40744, "longitude": -41.84599},
    {"external_id": "IMACA7", "name": "Macaé", "municipality": "Macaé", "latitude": -22.40713, "longitude": -41.84594},
    {"external_id": "IMANGA43", "name": "Mangaratiba", "municipality": "Angra dos Reis", "latitude": -22.92565, "longitude": -44.07865},
    {"external_id": "IMARIC14", "name": "Maricá", "municipality": "Itaboraí", "latitude": -22.95518, "longitude": -42.71384},
    {"external_id": "IMARIC16", "name": "Maricá", "municipality": "Itaboraí", "latitude": -22.96697, "longitude": -42.91351},
    {"external_id": "IMIMOS4", "name": "Mimoso do Sul", "municipality": "Bom Jesus do Itabapoana", "latitude": -21.07611, "longitude": -41.31991},
    {"external_id": "IMINASGE43", "name": "Pequeri", "municipality": "Comendador Levy Gasparian", "latitude": -21.86331, "longitude": -43.13578},
    {"external_id": "INOVAF18", "name": "Nova Friburgo", "municipality": "Cachoeiras de Macacu", "latitude": -22.35354, "longitude": -42.58707},
    {"external_id": "INOVAF23", "name": "Nova Friburgo", "municipality": "Bom Jardim", "latitude": -22.27538, "longitude": -42.48095},
    {"external_id": "INOVAF27", "name": "Nova Friburgo", "municipality": "Bom Jardim", "latitude": -22.23384, "longitude": -42.53723},
    {"external_id": "INOVAF28", "name": "Nova Friburgo", "municipality": "Bom Jardim", "latitude": -22.31564, "longitude": -42.54735},
    {"external_id": "INOVAF30", "name": "Nova Friburgo", "municipality": "Bom Jardim", "latitude": -22.28709, "longitude": -42.53403},
    {"external_id": "INOVAF31", "name": "Nova Friburgo", "municipality": "Bom Jardim", "latitude": -22.32888, "longitude": -42.46636},
    {"external_id": "INOVAF42", "name": "Nova Friburgo", "municipality": "Cachoeiras de Macacu", "latitude": -22.30672, "longitude": -42.59976},
    {"external_id": "INOVAI19", "name": "Nova Iguaçu", "municipality": "Belford Roxo", "latitude": -22.753, "longitude": -43.46},
    {"external_id": "INOVAI21", "name": "Nova Iguaçu", "municipality": "Belford Roxo", "latitude": -22.67262, "longitude": -43.47644},
    {"external_id": "IPARAB10", "name": "Paraíba do Sul", "municipality": "Areal", "latitude": -22.06588, "longitude": -43.33001},
    {"external_id": "IPARAB14", "name": "Paraíba do Sul", "municipality": "Areal", "latitude": -22.19675, "longitude": -43.17392},
    {"external_id": "IPASSA105", "name": "Passa-Vinte", "municipality": "Barra Mansa", "latitude": -22.19815, "longitude": -44.2545},
    {"external_id": "IPETRP11", "name": "Petrópolis", "municipality": "Areal", "latitude": -22.36973, "longitude": -43.13015},
    {"external_id": "IPETRP17", "name": "Petrópolis", "municipality": "Duque de Caxias", "latitude": -22.522, "longitude": -43.205},
    {"external_id": "IPETRP21", "name": "Petrópolis", "municipality": "Areal", "latitude": -22.30908, "longitude": -43.04771},
    {"external_id": "IPETRP25", "name": "Petrópolis", "municipality": "Belford Roxo", "latitude": -22.52825, "longitude": -43.21554},
    {"external_id": "IPETRP27", "name": "Petrópolis", "municipality": "Areal", "latitude": -22.25714, "longitude": -43.0573},
    {"external_id": "IPETRP35", "name": "Petrópolis", "municipality": "Areal", "latitude": -22.42808, "longitude": -43.08782},
    {"external_id": "IPETRP36", "name": "Petrópolis", "municipality": "Duque de Caxias", "latitude": -22.44419, "longitude": -43.32945},
    {"external_id": "IPETRP37", "name": "Petrópolis", "municipality": "Areal", "latitude": -22.4266, "longitude": -43.3237},
    {"external_id": "IPETRP7", "name": "Petrópolis", "municipality": "Duque de Caxias", "latitude": -22.496, "longitude": -43.205},
    {"external_id": "IRESEN10", "name": "Resende", "municipality": "Itatiaia", "latitude": -22.35883, "longitude": -44.50266},
    {"external_id": "IRESEN13", "name": "Resende", "municipality": "Itatiaia", "latitude": -22.37285, "longitude": -44.704},
    {"external_id": "IRESEN15", "name": "Resende", "municipality": "Itatiaia", "latitude": -22.42118, "longitude": -44.72877},
    {"external_id": "IRESEN17", "name": "Resende", "municipality": "Itatiaia", "latitude": -22.37692, "longitude": -44.7027},
    {"external_id": "IRESEN20", "name": "Resende", "municipality": "Itatiaia", "latitude": -22.32921, "longitude": -44.52773},
    {"external_id": "IRIOBO1", "name": "Rio Bonito", "municipality": "Araruama", "latitude": -22.70884, "longitude": -42.62648},
    {"external_id": "IRIOCL8", "name": "Rio Claro", "municipality": "Angra dos Reis", "latitude": -22.83148, "longitude": -44.19797},
    {"external_id": "IRIODE105", "name": "Rio de Janeiro", "municipality": "Belford Roxo", "latitude": -22.97068, "longitude": -43.39212},
    {"external_id": "IRIODE108", "name": "Rio de Janeiro", "municipality": "Belford Roxo", "latitude": -22.82874, "longitude": -43.37221},
    {"external_id": "IRIODE109", "name": "Rio de Janeiro", "municipality": "Rio de Janeiro", "latitude": -23.011, "longitude": -43.328},
    {"external_id": "IRIODE112", "name": "Rio de Janeiro", "municipality": "Itaguaí", "latitude": -22.91584, "longitude": -43.55959},
    {"external_id": "IRIODE113", "name": "Rio de Janeiro", "municipality": "Itaguaí", "latitude": -22.98376, "longitude": -43.49675},
    {"external_id": "IRIODE114", "name": "Rio de Janeiro", "municipality": "Itaboraí", "latitude": -22.93798, "longitude": -43.1829},
    {"external_id": "IRIODE122", "name": "Rio de Janeiro", "municipality": "Belford Roxo", "latitude": -22.87591, "longitude": -43.24805},
    {"external_id": "IRIODE130", "name": "Rio de Janeiro", "municipality": "Niterói", "latitude": -22.97067, "longitude": -43.22468},
    {"external_id": "IRIODE135", "name": "Rio de Janeiro", "municipality": "Itaboraí", "latitude": -22.935, "longitude": -43.179},
    {"external_id": "IRIODE144", "name": "Rio de Janeiro", "municipality": "Belford Roxo", "latitude": -22.79683, "longitude": -43.20086},
    {"external_id": "IRIODE146", "name": "Rio de Janeiro", "municipality": "Rio de Janeiro", "latitude": -23.03109, "longitude": -43.33812},
    {"external_id": "IRIODE149", "name": "Rio de Janeiro", "municipality": "Belford Roxo", "latitude": -22.865, "longitude": -43.229},
    {"external_id": "IRIODE150", "name": "Rio de Janeiro", "municipality": "Itaboraí", "latitude": -22.94851, "longitude": -43.17892},
    {"external_id": "IRIODE157", "name": "Rio de Janeiro", "municipality": "Maricá", "latitude": -22.96192, "longitude": -43.20245},
    {"external_id": "IRIODE159", "name": "Rio de Janeiro", "municipality": "Rio de Janeiro", "latitude": -23.01, "longitude": -43.319},
    {"external_id": "IRIODE165", "name": "Rio de Janeiro", "municipality": "Queimados", "latitude": -23.01586, "longitude": -43.45978},
    {"external_id": "IRIODE170", "name": "Rio de Janeiro", "municipality": "Itaboraí", "latitude": -22.93, "longitude": -43.177},
    {"external_id": "IRIODE81", "name": "Rio de Janeiro", "municipality": "Itaguaí", "latitude": -23.0, "longitude": -43.605},
    {"external_id": "IRIODE85", "name": "Rio de Janeiro", "municipality": "Belford Roxo", "latitude": -22.793, "longitude": -43.18},
    {"external_id": "IRIODE89", "name": "Rio de Janeiro", "municipality": "Maricá", "latitude": -22.965, "longitude": -43.183},
    {"external_id": "IRIODE90", "name": "Rio de Janeiro", "municipality": "Belford Roxo", "latitude": -22.865, "longitude": -43.229},
    {"external_id": "IRIODE96", "name": "Rio de Janeiro", "municipality": "Nilópolis", "latitude": -22.98336, "longitude": -43.30811},
    {"external_id": "IRIODEJA96", "name": "Rio De Janeiro", "municipality": "Niterói", "latitude": -22.98195, "longitude": -43.22173},
    {"external_id": "ISEROP9", "name": "Seropédica", "municipality": "Engenheiro Paulo de Frontin", "latitude": -22.699, "longitude": -43.649},
    {"external_id": "ISOPAULO82", "name": "São José Do Barreiro", "municipality": "Angra dos Reis", "latitude": -22.70542, "longitude": -44.62803},
    {"external_id": "ITERES23", "name": "Teresópolis", "municipality": "Cachoeiras de Macacu", "latitude": -22.37182, "longitude": -42.86937},
    {"external_id": "ITERES38", "name": "Teresópolis", "municipality": "Cachoeiras de Macacu", "latitude": -22.30064, "longitude": -42.81629},
    {"external_id": "ITERES48", "name": "Teresópolis", "municipality": "Areal", "latitude": -22.42858, "longitude": -42.97821},
    {"external_id": "ITERES52", "name": "Teresópolis", "municipality": "Areal", "latitude": -22.38998, "longitude": -42.90872},
    {"external_id": "IVALEN513", "name": "Valença", "municipality": "Barra do Piraí", "latitude": -22.36756, "longitude": -43.85295},
    {"external_id": "IVALEN520", "name": "Valença", "municipality": "Barra Mansa", "latitude": -22.230437, "longitude": -44.047661},
    {"external_id": "IVALEN530", "name": "Valença", "municipality": "Barra do Piraí", "latitude": -22.28074, "longitude": -43.74289},
    {"external_id": "IVOLTA15", "name": "Volta Redonda", "municipality": "Barra do Piraí", "latitude": -22.49598, "longitude": -44.07209},
]


class WundergroundConnector(BaseConnector):
    slug = "wunderground"
    name = "Weather Underground (PWS)"
    website = "https://www.wunderground.com/"
    description = "Estações PWS indicadas pelas Defesas Civis municipais (Rio das Ostras, Casimiro de Abreu, Macaé e região)."

    def fetch_stations(self) -> list[dict]:
        return [
            {
                "external_id": s["external_id"],
                "name": s["name"],
                "municipality": s["municipality"],
                "station_type": Station.StationType.METEOROLOGICA,
                "status": Station.Status.DESCONHECIDO,
                "latitude": s["latitude"],
                "longitude": s["longitude"],
                "altitude_m": None,
                "raw_metadata": s,
            }
            for s in STATIONS_RJ
        ]

    def fetch_readings(self, stations: list[dict]) -> list[dict]:
        api_key = getattr(settings, "WUNDERGROUND_API_KEY", "")
        if not api_key:
            logger.info("WUNDERGROUND_API_KEY não configurado — pulando leituras do Wunderground.")
            return []

        readings: list[dict] = []
        for st in stations:
            codigo = st["external_id"]
            try:
                resp = requests.get(
                    CURRENT_URL,
                    params={
                        "stationId": codigo,
                        "format": "json",
                        "units": "m",
                        "numericPrecision": "decimal",
                        "apiKey": api_key,
                    },
                    timeout=15,
                )
                if resp.status_code == 204:
                    continue  # estação sem leitura recente (comum, não é erro)
                resp.raise_for_status()
                payload = resp.json()
            except Exception:  # noqa: BLE001
                logger.exception("Falha ao buscar leitura Wunderground de %s", codigo)
                continue

            observacoes = payload.get("observations") or []
            if not observacoes:
                continue
            obs = observacoes[0]
            timestamp = _parse_timestamp(obs.get("obsTimeUtc"))
            if timestamp is None:
                continue

            metric = obs.get("metric") or {}

            def add(reading_type, valor):
                if valor is None:
                    return
                readings.append(
                    {
                        "external_id": codigo,
                        "reading_type": reading_type,
                        "value": float(valor),
                        "timestamp": timestamp,
                        "raw_payload": obs,
                    }
                )

            add(Reading.ReadingType.TEMPERATURA_C, metric.get("temp"))
            add(Reading.ReadingType.UMIDADE_PCT, obs.get("humidity"))
            # precipTotal é corrido desde a meia-noite local, não um valor
            # por-janela — convertido pra "balde" (chuva NESSE intervalo),
            # comparando com o que já guardamos hoje pra essa estação, pra
            # ficar escalonado igual às fontes tipo "balde" (ver
            # bucket_from_running_daily em base.py e
            # PRECIPITACAO_BUCKET_SOURCES em api/views.py).
            precip_total = metric.get("precipTotal")
            if precip_total is not None:
                add(Reading.ReadingType.CHUVA_MM, bucket_from_running_daily("wunderground", codigo, float(precip_total)))
            add(Reading.ReadingType.VENTO_DIR_GRAUS, obs.get("winddir"))
            # windSpeed/windGust vêm em km/h (convenção "metric" da Weather
            # Company) — convertendo para m/s para bater com o padrão do
            # resto do projeto (Reading.ReadingType.VENTO_MS).
            vento_kmh = metric.get("windSpeed")
            if vento_kmh is not None:
                add(Reading.ReadingType.VENTO_MS, vento_kmh / 3.6)
            rajada_kmh = metric.get("windGust")
            if rajada_kmh is not None:
                add(Reading.ReadingType.VENTO_RAJADA_MS, rajada_kmh / 3.6)

        return readings


def _parse_timestamp(valor: str | None) -> dt.datetime | None:
    if not valor:
        return None
    try:
        return dt.datetime.strptime(valor, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        logger.warning("Timestamp Wunderground inesperado: %r", valor)
        return None
