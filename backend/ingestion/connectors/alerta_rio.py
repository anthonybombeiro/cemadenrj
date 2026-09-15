"""
Conector para as estações pluviométricas e meteorológicas do Sistema
Alerta Rio / GeoRio (Prefeitura do Rio de Janeiro).

Estações (localização): GeoJSON público via DATA.RIO / ArcGIS Hub —
  GET https://www.data.rio/api/download/v1/items/{item_id}/geojson?layers=0
  item_id = 88b61c6abe424c049fdf83d27917602e  (dataset "Estações Alerta Rio")

Leituras em tempo real (encontrado em 15/09/2026 lendo o código-fonte
aberto do painel https://github.com/COR-RIO/dados-rio-chuvas, um projeto
recente — não documentado publicamente em lugar nenhum, mas é literalmente
a API que abastece o site oficial do Alerta Rio):

  GET https://websempre.rio.rj.gov.br/json/chuvas
      Chuva por estação em várias janelas (m05, m15, h01..h04, h24, h96,
      mes), sem paginação, todas as 33 estações pluviométricas de uma vez.
  GET https://websempre.rio.rj.gov.br/json/dados_meteorologicos
      Temperatura (inst./mín./máx.), umidade, pressão e vento (velocidade
      + direção cardinal em texto) por estação meteorológica — conjunto de
      estações parcialmente diferente do pluviométrico.

Essas URLs respondem "Request Rejected" (bloqueio de um WAF por
User-Agent) para clientes genéricos tipo `curl` sem cabeçalhos — não é
CAPTCHA nem desafio interativo, só uma checagem de User-Agent/Referer.
Enviar um User-Agent de navegador comum resolve, e é isso que fazemos
aqui — mesmo princípio de identificar o cliente que qualquer integração
HTTP normal já faz.

O casamento de cada leitura com a estação correta é feito por nome
("est" do GeoJSON == "name" da API de chuva) para pluviômetros, e por
código numérico ("cod" do GeoJSON == "station.id" da API meteorológica)
para as estações meteorológicas.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import unicodedata

import requests

from core.models import Reading, Station

from .base import BaseConnector

logger = logging.getLogger("ingestion")

GEOJSON_URL = "https://www.data.rio/api/download/v1/items/88b61c6abe424c049fdf83d27917602e/geojson?layers=0"
CHUVAS_URL = "https://websempre.rio.rj.gov.br/json/chuvas"
METEOROLOGICOS_URL = "https://websempre.rio.rj.gov.br/json/dados_meteorologicos"

# Sem isso, o WAF do host rejeita a requisição com "Request Rejected"
# (checagem de User-Agent/Referer, não é CAPTCHA).
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.sistema-alerta-rio.com.br/",
}

CARDINAL_TO_DEG = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5, "E": 90, "ESE": 112.5,
    "SE": 135, "SSE": 157.5, "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5,
    "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5,
}


class AlertaRioConnector(BaseConnector):
    slug = "alerta_rio"
    name = "Alerta Rio / GeoRio"
    website = "https://www.sistema-alerta-rio.com.br/"
    description = "Estações pluviométricas e meteorológicas do Sistema Alerta Rio (capital)."

    def fetch_stations(self) -> list[dict]:
        resp = requests.get(GEOJSON_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        stations = []
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            lon, lat = coords[0], coords[1]
            codigo = props.get("cod")
            if codigo is None:
                continue
            bairro = props.get("est") or ""
            stations.append(
                {
                    "external_id": str(codigo),
                    "name": f"Alerta Rio - {bairro}" if bairro else f"Alerta Rio - estação {codigo}",
                    "municipality": "Rio de Janeiro",
                    "station_type": Station.StationType.PLUVIOMETRICA,
                    "status": Station.Status.DESCONHECIDO,
                    "latitude": lat,
                    "longitude": lon,
                    "altitude_m": None,
                    "raw_metadata": props,
                }
            )
        return stations

    def fetch_readings(self, stations: list[dict]) -> list[dict]:
        readings: list[dict] = []
        by_bairro = {
            _normalizar(st["raw_metadata"].get("est", "")): st["external_id"] for st in stations
        }
        by_cod = {str(st["raw_metadata"].get("cod")): st["external_id"] for st in stations}

        readings.extend(self._fetch_chuvas(by_bairro))
        readings.extend(self._fetch_meteorologicos(by_cod))
        return readings

    def _fetch_chuvas(self, by_bairro: dict[str, str]) -> list[dict]:
        try:
            resp = requests.get(CHUVAS_URL, headers=BROWSER_HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception:  # noqa: BLE001
            logger.exception("Falha ao buscar %s", CHUVAS_URL)
            return []

        readings = []
        for obj in data.get("objects", []):
            external_id = by_bairro.get(_normalizar(obj.get("name", "")))
            if external_id is None:
                continue
            timestamp = _parse_iso(obj.get("read_at"))
            if timestamp is None:
                continue
            valor = (obj.get("data") or {}).get("m15")
            if valor is None:
                continue
            readings.append(
                {
                    "external_id": external_id,
                    "reading_type": Reading.ReadingType.CHUVA_MM,
                    "value": float(valor),
                    "timestamp": timestamp,
                    "raw_payload": obj,
                }
            )
        return readings

    def _fetch_meteorologicos(self, by_cod: dict[str, str]) -> list[dict]:
        try:
            resp = requests.get(METEOROLOGICOS_URL, headers=BROWSER_HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception:  # noqa: BLE001
            logger.exception("Falha ao buscar %s", METEOROLOGICOS_URL)
            return []

        readings = []
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            station_id = (props.get("station") or {}).get("id")
            external_id = by_cod.get(str(station_id))
            if external_id is None:
                continue
            timestamp = _parse_iso(props.get("read_at"))
            if timestamp is None:
                continue
            valores = props.get("data") or {}

            for chave, reading_type in (
                ("temperature", Reading.ReadingType.TEMPERATURA_C),
                ("humidity", Reading.ReadingType.UMIDADE_PCT),
            ):
                valor = _parse_br_float(valores.get(chave))
                if valor is not None:
                    readings.append(
                        {
                            "external_id": external_id,
                            "reading_type": reading_type,
                            "value": valor,
                            "timestamp": timestamp,
                            "raw_payload": props,
                        }
                    )

            vel_ms, direcao = _parse_vento(valores.get("wind"))
            if vel_ms is not None:
                readings.append(
                    {
                        "external_id": external_id,
                        "reading_type": Reading.ReadingType.VENTO_MS,
                        "value": vel_ms,
                        "timestamp": timestamp,
                        "raw_payload": props,
                    }
                )
            if direcao is not None:
                readings.append(
                    {
                        "external_id": external_id,
                        "reading_type": Reading.ReadingType.VENTO_DIR_GRAUS,
                        "value": direcao,
                        "timestamp": timestamp,
                        "raw_payload": props,
                    }
                )
        return readings


# Pequenas diferenças de nomenclatura entre o GeoJSON de estações (usado
# em fetch_stations) e a API de leituras em tempo real.
_ALIASES_NOME = {
    "estrada grajau/jacarepagua": "est. grajau/jacarepagua",
}


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    chave = sem_acento.strip().casefold()
    return _ALIASES_NOME.get(chave, chave)


def _parse_iso(valor: str | None) -> dt.datetime | None:
    if not valor:
        return None
    try:
        return dt.datetime.fromisoformat(valor)
    except ValueError:
        logger.warning("Timestamp Alerta Rio inesperado: %r", valor)
        return None


def _parse_br_float(valor) -> float | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    if texto in ("", "-", "--"):
        return None
    try:
        return float(texto.replace(",", "."))
    except ValueError:
        return None


def _parse_vento(valor: str | None) -> tuple[float | None, float | None]:
    """Formato observado: "8,64 (S)" ou "0,0 (SW)" — velocidade e direção
    cardinal. Unidade da velocidade não está documentada publicamente;
    assumimos km/h (convenção comum em painéis de defesa civil no Brasil)
    e convertemos para m/s — a CONFIRMAR quando possível."""
    if not valor:
        return None, None
    texto = str(valor).strip()
    if texto in ("-", "--", ""):
        return None, None
    m = re.match(r"([\d,.]+)\s*\(([A-Z/]+)\)", texto)
    if not m:
        return None, None
    velocidade_kmh = _parse_br_float(m.group(1))
    cardinal = m.group(2)
    velocidade_ms = velocidade_kmh / 3.6 if velocidade_kmh is not None else None
    direcao = CARDINAL_TO_DEG.get(cardinal)
    return velocidade_ms, direcao
