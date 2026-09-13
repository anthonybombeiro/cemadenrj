"""
Conector para o WebService nacional do CEMADEN (rede de pluviômetros e
estações hidrológicas), documentado em "WebService – Disponibilização de
dados da rede pluviométrica e Hidrológica Cemaden" (Cemaden, v2.0):

  GET {CEMADEN_NACIONAL_BASE_URL}/{UF}/{tipo}
  tipo: 1 = Pluviométrica, 3 = Hidrológica

Exemplo de item retornado (conforme o documento oficial):
  {"codestacao": "120040101A", "latitude": -9.97, "longitude": -67.80,
   "cidade": "RIO BRANCO", "nome": "AC Oca", "tipo": "Pluviométrica",
   "uf": "AC", "chuva": 0.0, "nivel": null, "dataHora": "2015-02-04 13:00:00.0"}

Só entrega as últimas 3 horas de dados (limitação documentada pelo próprio
Cemaden, para não sobrecarregar a infraestrutura deles) — por isso a
ingestão precisa rodar com frequência (a cada 10-15 min) para não perder
janelas de leitura.

IMPORTANTE: o endereço documentado é um IP direto da rede do INPE/Cemaden
(150.163.255.240), não um domínio público, e não respondeu a partir do
ambiente de desenvolvimento usado para montar este projeto (timeout —
pode ser bloqueio de rede local ou o endereço ter mudado desde 2015).
Precisa ser validado a partir do servidor de produção; se não responder,
contatar o Cemaden (grupo de sistemas, e-mail no documento de referência
em docs/fontes-de-dados.md) para confirmar o endereço atual.
"""

from __future__ import annotations

import datetime as dt
import logging

import requests
from django.conf import settings

from core.models import Reading, Station

from .base import BaseConnector

logger = logging.getLogger("ingestion")

UF_ALVO = "RJ"
TIPO_PLUVIOMETRICA = "1"
TIPO_HIDROLOGICA = "3"


class CemadenNacionalConnector(BaseConnector):
    slug = "cemaden_nacional"
    name = "CEMADEN Nacional"
    website = "http://www2.cemaden.gov.br/"
    description = "Rede nacional de pluviômetros e estações hidrológicas do CEMADEN, filtrada para o RJ."

    def _base_url(self) -> str:
        return getattr(settings, "CEMADEN_NACIONAL_BASE_URL", "").rstrip("/")

    def _fetch_tipo(self, tipo: str) -> list[dict]:
        base = self._base_url()
        if not base:
            return []
        url = f"{base}/{UF_ALVO}/{tipo}"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("cemaden", []) if isinstance(payload, dict) else payload

    def fetch_stations(self) -> list[dict]:
        stations_by_id: dict[str, dict] = {}
        for tipo, station_type in (
            (TIPO_PLUVIOMETRICA, Station.StationType.PLUVIOMETRICA),
            (TIPO_HIDROLOGICA, Station.StationType.HIDROLOGICA),
        ):
            try:
                items = self._fetch_tipo(tipo)
            except Exception:  # noqa: BLE001
                logger.exception("Falha ao buscar estações CEMADEN nacional (tipo=%s)", tipo)
                continue
            for item in items:
                codigo = item.get("codestacao")
                if not codigo:
                    continue
                stations_by_id[codigo] = {
                    "external_id": codigo,
                    "name": item.get("nome") or codigo,
                    "municipality": (item.get("cidade") or "").title(),
                    "station_type": station_type,
                    "status": Station.Status.ATIVA,
                    "latitude": item.get("latitude"),
                    "longitude": item.get("longitude"),
                    "altitude_m": None,
                    "raw_metadata": item,
                    "_tipo": tipo,
                }
        return [s for s in stations_by_id.values() if s["latitude"] is not None and s["longitude"] is not None]

    def fetch_readings(self, stations: list[dict]) -> list[dict]:
        readings = []
        for st in stations:
            item = st["raw_metadata"]
            timestamp = _parse_timestamp(item.get("dataHora"))
            if timestamp is None:
                continue
            if st["_tipo"] == TIPO_PLUVIOMETRICA and item.get("chuva") is not None:
                readings.append(
                    {
                        "external_id": st["external_id"],
                        "reading_type": Reading.ReadingType.CHUVA_MM,
                        "value": float(item["chuva"]),
                        "timestamp": timestamp,
                        "raw_payload": item,
                    }
                )
            if st["_tipo"] == TIPO_HIDROLOGICA and item.get("nivel") is not None:
                readings.append(
                    {
                        "external_id": st["external_id"],
                        "reading_type": Reading.ReadingType.NIVEL_M,
                        "value": float(item["nivel"]),
                        "timestamp": timestamp,
                        "raw_payload": item,
                    }
                )
        return readings


def _parse_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(value, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    logger.warning("Timestamp CEMADEN inesperado: %r", value)
    return None
