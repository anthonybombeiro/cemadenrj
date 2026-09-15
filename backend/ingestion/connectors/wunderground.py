"""
Conector para estações pessoais (PWS) do Weather Underground / The Weather
Company (IBM) no estado do RJ.

Ao contrário de uma tentativa anterior (descartada) de descobrir a rede
inteira de estações por engenharia reversa, este conector só consulta
códigos de estação específicos e já conhecidos — passados diretamente
pelas Defesas Civis municipais de Rio das Ostras, Casimiro de Abreu e
Macaé (mais Armação dos Búzios, Cabo Frio, Arraial do Cabo e Nova Friburgo,
usadas por essas Defesas Civis para monitoramento regional/de bacia). Essa
é a forma pretendida de uso da API: consultar dados de estações cujo ID
você já tem, com uma chave de API própria (não a chave pública embutida no
site, usada só numa investigação inicial e descartada).

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

from .base import BaseConnector

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
            add(Reading.ReadingType.CHUVA_MM, metric.get("precipTotal"))
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
