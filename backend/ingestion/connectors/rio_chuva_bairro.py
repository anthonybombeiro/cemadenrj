"""
Conector para a API oficial e aberta do Escritório de Dados da Prefeitura
do Rio de Janeiro (COR — Centro de Operações Rio), que agrega os dados de
chuva da rede Alerta Rio/CEMADEN por bairro (hexágonos H3), preenchendo a
lacuna de leituras em tempo real do Alerta Rio (o `alerta_rio.py` só tem a
localização das 33 estações, sem leituras — a página de dados deles é
protegida por Cloudflare, que não tentamos contornar).

100% legítimo e documentado: API pública, sem autenticação, código-fonte
aberto em https://github.com/prefeitura-rio/api-dados-rio (GPLv3),
mantida pelo Escritório de Dados (escritoriodedados@gmail.com). Descoberta
via busca no data.rio + no GitHub da Prefeitura, não por engenharia
reversa de nada protegido.

Endpoint usado (dos vários disponíveis — ver módulo `clima_pluviometro`
no repositório acima):
  GET https://api.dados.rio/v2/clima_pluviometro/precipitacao_15min/
  GET https://api.dados.rio/v2/clima_pluviometro/ultima_atualizacao_precipitacao_15min/

Retorna a chuva dos últimos 15 minutos por hexágono H3 (cobre só o
município do Rio de Janeiro, não o estado inteiro):
  [{"id_h3": "88a8a03989fffff", "bairro": "Guaratiba", "chuva_15min": 0.0,
    "estacoes": null, "status": "sem chuva", "color": "#ffffff"}, ...]

O hexágono H3 é convertido para lat/lon (centro) com a biblioteca `h3`
para exibição no mapa. Outras janelas de tempo (30min, 1h, 3h, 6h, 12h,
24h, 96h) existem na mesma API mas não são usadas aqui ainda.

IMPORTANTE: serviço observado fora do ar (HTTP 503) em 15/09/2026 durante
o desenvolvimento deste conector — o repositório no GitHub estava com
commit do dia anterior, então não parece abandonado. Erros de conexão são
tratados normalmente (log + lista vazia), sem derrubar o restante da
ingestão.
"""

from __future__ import annotations

import datetime as dt
import logging

import requests

from core.models import Reading, Station

from .base import BaseConnector

logger = logging.getLogger("ingestion")

BASE_URL = "https://api.dados.rio/v2/clima_pluviometro"
PRECIPITACAO_15MIN_URL = f"{BASE_URL}/precipitacao_15min/"
ULTIMA_ATUALIZACAO_URL = f"{BASE_URL}/ultima_atualizacao_precipitacao_15min/"

# America/Sao_Paulo não tem horário de verão desde 2019 — offset fixo.
BRT_OFFSET = dt.timedelta(hours=-3)


class RioChuvaBairroConnector(BaseConnector):
    slug = "rio_chuva_bairro"
    name = "Chuva por Bairro — Escritório de Dados Rio (COR)"
    website = "https://api.dados.rio/docs/"
    description = "Precipitação dos últimos 15 min por bairro/hexágono H3, agregada pelo COR a partir da rede Alerta Rio/CEMADEN no município do Rio."

    def fetch_stations(self) -> list[dict]:
        import h3

        resp = requests.get(PRECIPITACAO_15MIN_URL, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            logger.warning("Resposta inesperada de precipitacao_15min: %r", data)
            return []

        stations = []
        for item in data:
            id_h3 = item.get("id_h3")
            if not id_h3:
                continue
            try:
                lat, lon = h3.cell_to_latlng(id_h3)
            except Exception:  # noqa: BLE001
                logger.warning("Não foi possível converter hexágono H3 %r para lat/lon.", id_h3)
                continue
            stations.append(
                {
                    "external_id": id_h3,
                    "name": item.get("bairro") or id_h3,
                    "municipality": "Rio de Janeiro",
                    "station_type": Station.StationType.PLUVIOMETRICA,
                    "status": Station.Status.ATIVA,
                    "latitude": lat,
                    "longitude": lon,
                    "altitude_m": None,
                    "raw_metadata": item,
                }
            )
        return stations

    def fetch_readings(self, stations: list[dict]) -> list[dict]:
        try:
            resp = requests.get(PRECIPITACAO_15MIN_URL, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception:  # noqa: BLE001
            logger.exception("Falha ao buscar precipitacao_15min do Escritório de Dados Rio.")
            return []

        timestamp = self._fetch_timestamp() or dt.datetime.now(dt.timezone.utc)

        readings = []
        for item in data if isinstance(data, list) else []:
            id_h3 = item.get("id_h3")
            valor = item.get("chuva_15min")
            if not id_h3 or valor is None:
                continue
            readings.append(
                {
                    "external_id": id_h3,
                    "reading_type": Reading.ReadingType.CHUVA_MM,
                    "value": float(valor),
                    "timestamp": timestamp,
                    "raw_payload": item,
                }
            )
        return readings

    def _fetch_timestamp(self) -> dt.datetime | None:
        try:
            resp = requests.get(ULTIMA_ATUALIZACAO_URL, timeout=20)
            resp.raise_for_status()
            texto = resp.json()
            if not isinstance(texto, str):
                return None
            naive = dt.datetime.strptime(texto.strip(), "%d/%m/%Y %H:%M:%S")
            return (naive - BRT_OFFSET).replace(tzinfo=dt.timezone.utc)
        except Exception:  # noqa: BLE001
            logger.warning("Não foi possível obter o horário de atualização; usando 'agora'.")
            return None
