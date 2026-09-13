"""
Conector para as estações pluviométricas do Sistema Alerta Rio / GeoRio
(Prefeitura do Rio de Janeiro).

Confirmado nesta sessão: a localização das 33 estações está disponível,
sem autenticação, como GeoJSON público via o portal de dados abertos da
prefeitura (DATA.RIO / ArcGIS Hub):

  GET https://www.data.rio/api/download/v1/items/{item_id}/geojson?layers=0
  item_id = 88b61c6abe424c049fdf83d27917602e  (dataset "Estações Alerta Rio")

Isso dá posição e identificação das estações (bairro, endereço, código),
o que já é suficiente para colocá-las no mapa unificado.

O que NÃO foi confirmado: um endpoint JSON público para as leituras de
chuva em tempo real. A página https://www.sistema-alerta-rio.com.br
("Registros em tempo real"/"tabela-de-dados") parece publicar isso como
tabela HTML e bloqueou uma requisição simples (HTTP 403 — provável
proteção antibot). Duas opções para destravar isso, a tratar como parte
do contato institucional já em andamento com a Defesa Civil-RJ/GridLab
(que também opera o Alerta Rio):
  1. Pedir formalmente ao GeoRio/Alerta Rio um feed ou API dos dados de
     chuva (e-mail de contato: alertario@centrodeoperacoesrio.com.br).
  2. Como alternativa técnica, fazer scraping da tabela HTML com um
     User-Agent de navegador real — mais frágil (quebra se o layout do
     site mudar) e por isso não implementado aqui sem validação humana.

Por ora, `fetch_readings` retorna lista vazia propositalmente.
"""

from __future__ import annotations

import logging

import requests

from core.models import Station

from .base import BaseConnector

logger = logging.getLogger("ingestion")

GEOJSON_URL = "https://www.data.rio/api/download/v1/items/88b61c6abe424c049fdf83d27917602e/geojson?layers=0"


class AlertaRioConnector(BaseConnector):
    slug = "alerta_rio"
    name = "Alerta Rio / GeoRio"
    website = "https://www.sistema-alerta-rio.com.br/"
    description = "Estações pluviométricas do Sistema Alerta Rio (33 estações na capital)."

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
        logger.info(
            "Conector Alerta Rio: leituras em tempo real ainda não têm endpoint público "
            "confirmado — ver docstring do módulo. Retornando lista vazia."
        )
        return []
