"""
Conector para a rede de pluviômetros da Defesa Civil de Niterói
(plataforma "Alerta Nit", operada pela Tecal — fornecida pelo usuário,
diretor do CEMADEN-RJ, em setembro/2026).

  GET http://alertanit.tecal.com.br/estacoes/rest/stations/
      GeoJSON (FeatureCollection) com todas as estações — id, nome,
      código, tipo ("plv" = pluviômetro), latitude/longitude exata.
  GET http://alertanit.tecal.com.br/dados/rest/last_leituras/
      Última leitura de cada estação (por "estacao" = id da estação),
      já com chuva acumulada em várias janelas prontas: m05, m10, m15,
      m30, h01, h06, h12, h24, h36, h48, h72, h96, h168, h720, mes.

Autenticação: HTTP Basic (usuário/senha institucional, configurar em
NITEROI_API_USERNAME/NITEROI_API_PASSWORD no `.env` — nunca no código).

Guardamos "m05" (chuva acumulada nos últimos 5 min) como `chuva_mm` — é a
janela mais fina disponível, tratada como "balde" (soma ao longo do tempo
é válida) pro nosso próprio cálculo de acumulados em `api/views.py`
(`PRECIPITACAO_BUCKET_SOURCES`). As janelas maiores que a API já entrega
prontas (h24, h96, mes, ...) não são usadas diretamente, mesmo motivo
documentado em `cemaden_rj_pluviometros.py`: consistência com as outras
fontes em vez de um campo especial só pra essa.
"""

from __future__ import annotations

import datetime as dt
import logging

import requests
from django.conf import settings

from core.models import Reading, Station

from .base import BaseConnector

logger = logging.getLogger("ingestion")

BASE_URL = "http://alertanit.tecal.com.br"
STATIONS_URL = f"{BASE_URL}/estacoes/rest/stations/"
READINGS_URL = f"{BASE_URL}/dados/rest/last_leituras/"


class NiteroiConnector(BaseConnector):
    slug = "niteroi"
    name = "Niterói — Defesa Civil Municipal (Alerta Nit/Tecal)"
    website = BASE_URL
    description = "Rede de pluviômetros da Defesa Civil de Niterói, plataforma Alerta Nit (Tecal)."

    def _auth(self) -> tuple[str, str] | None:
        username = getattr(settings, "NITEROI_API_USERNAME", "")
        password = getattr(settings, "NITEROI_API_PASSWORD", "")
        if not (username and password):
            logger.info("NITEROI_API_USERNAME/NITEROI_API_PASSWORD não configurados — pulando Niterói.")
            return None
        return (username, password)

    def fetch_stations(self) -> list[dict]:
        auth = self._auth()
        if auth is None:
            return []

        resp = requests.get(STATIONS_URL, auth=auth, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        stations = []
        for feature in payload.get("features", []):
            props = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            coords = geometry.get("coordinates")
            if not coords or len(coords) < 2:
                continue
            external_id = str(feature.get("id"))
            lon, lat = coords[0], coords[1]  # GeoJSON é [lon, lat]
            stations.append(
                {
                    "external_id": external_id,
                    "name": props.get("nome") or f"Niterói {external_id}",
                    "municipality": "Niterói",
                    "station_type": Station.StationType.PLUVIOMETRICA,
                    "status": Station.Status.ATIVA,
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "altitude_m": None,
                    "raw_metadata": props,
                }
            )
        return stations

    def fetch_readings(self, stations: list[dict]) -> list[dict]:
        auth = self._auth()
        if auth is None:
            return []

        resp = requests.get(READINGS_URL, auth=auth, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        readings = []
        for item in payload:
            timestamp = _parse_timestamp(item.get("horaLeitura"))
            if timestamp is None:
                continue
            valor = item.get("m05")
            if valor is None:
                continue
            readings.append(
                {
                    "external_id": str(item.get("estacao")),
                    "reading_type": Reading.ReadingType.CHUVA_MM,
                    "value": float(valor),
                    "timestamp": timestamp,
                    "raw_payload": item,
                }
            )
        return readings


def _parse_timestamp(valor: str | None) -> dt.datetime | None:
    if not valor:
        return None
    try:
        return dt.datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Timestamp Niterói inesperado: %r", valor)
        return None
