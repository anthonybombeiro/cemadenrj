"""
Conector para a tabela pública de pluviômetros do Sistema de Alerta e
Alarme Sonoro (rede de sirenes do estado), hospedado no domínio do
CBMERJ mas operado pelo CEMADEN-RJ (confirmado pelo usuário — diretor do
CEMADEN-RJ — em setembro/2026: o CBMERJ só empresta domínio/servidor,
ambos são órgãos da mesma Secretaria de Estado de Defesa Civil).

  GET http://sirene.cbmerj.rj.gov.br:8080/sirenesestadorj/ConsultaPluviometros
      ?cmd=dadosPluviometrosTotal

Página HTML pública, SEM login (testado direto, sem sessão/cookie),
contendo uma tabela (`id="chuva-limits"`) com uma linha por estação e
colunas: Fonte, Redec, Cidade, Estação, 15 Min, 1 Hora, 24 Horas,
96 Horas, 1 Mês, Geo (ícone de status), Data e Hora.

A coluna "Fonte" mistura estações de origens diferentes na mesma tabela —
por isso este arquivo define 2 conectores, um por fonte, cada um filtrando
sua parte:
  - CEMADEN RJ     → slug "cemaden_rj"     (~85 estações — rede PRÓPRIA do
    estado, nunca tínhamos acesso direto a isso antes; é o pedido original
    deste projeto desde o início)
  - CEMADEN MCTIC   → slug "cemaden_mctic"  (~247 estações — mesma rede
    nacional do `cemaden_nacional.py`, mas por este canal; o endpoint
    documentado oficial do CEMADEN nacional está fora do ar há meses, esse
    aqui funciona de verdade)

(A tabela também traz ~30 estações de "NITERÓI", mas essas têm uma API
própria — GeoJSON de verdade, com latitude/longitude exata por estação —
usada em `niteroi.py` em vez de aproximar pelo centroide do município
como é feito aqui.)

Sem latitude/longitude na tabela — só Redec/Cidade/Estação. Aproximamos
com o centroide do município (`ingestion/data/rj_municipios_centroides.json`,
calculado a partir da malha do IBGE — ver frontend/src/lib/geo.ts pro
equivalente do lado do frontend). `raw_metadata["coordenadas_aproximadas"]`
fica True pra deixar isso rastreável — não é a posição exata do
pluviômetro, é o centro do município. Dá pra estação aparecer no mapa,
mas não usar isso pra nada que precise de precisão de local.

"15 Min" é o valor que guardamos como `chuva_mm` — é chuva NA janela dos
últimos 15 min (tipo "balde", igual Alerta Rio/INMET — ver
`PRECIPITACAO_BUCKET_SOURCES` em `api/views.py`, onde esses 3 slugs
precisam ser adicionados). As janelas maiores (1h/24h/96h/1mês) que a
própria tabela já entrega prontas NÃO são usadas diretamente — preferimos
deixar nosso próprio endpoint de acumulado (que soma os "15 Min" ao longo
do tempo) calcular do jeito consistente com as outras fontes, mesmo que
isso signifique um "aquecimento" de até 4 dias pra 96h ficar completo.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from core.models import Reading, Station

from .base import BaseConnector

logger = logging.getLogger("ingestion")

URL = "http://sirene.cbmerj.rj.gov.br:8080/sirenesestadorj/ConsultaPluviometros?cmd=dadosPluviometrosTotal"
TZ_RJ = ZoneInfo("America/Sao_Paulo")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
}

_CENTROIDES_PATH = Path(__file__).resolve().parent.parent / "data" / "rj_municipios_centroides.json"
_centroides_cache: dict[str, list[float]] | None = None

# Cache só pra evitar buscar a mesma página HTML (>600KB) duas vezes dentro
# do MESMO processo — fetch_stations() e fetch_readings() são chamados em
# sequência por BaseConnector.run() e parseiam a mesma tabela. Não
# sobrevive entre requisições diferentes (cada ingest roda num processo CGI
# novo em produção), então não precisa de expiração por tempo.
_tabela_cache: list[dict] | None = None


def _normaliza(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(sem_acento.upper().split())


def _centroide_municipio(cidade: str) -> tuple[float, float] | None:
    global _centroides_cache
    if _centroides_cache is None:
        _centroides_cache = json.loads(_CENTROIDES_PATH.read_text(encoding="utf-8"))
    par = _centroides_cache.get(_normaliza(cidade))
    if par is None:
        return None
    return par[0], par[1]


def _to_float(valor: str) -> float | None:
    texto = (valor or "").strip().replace(",", ".")
    if not texto or texto in ("-", "--"):
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def _parse_data_hora(valor: str) -> dt.datetime | None:
    valor = (valor or "").strip()
    try:
        naive = dt.datetime.strptime(valor, "%d/%m/%Y %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=TZ_RJ).astimezone(dt.timezone.utc)


def _fetch_tabela() -> list[dict]:
    """Baixa e faz parsing da tabela `chuva-limits` uma vez por processo.
    Retorna uma linha por estação, já com os campos nomeados."""
    global _tabela_cache
    if _tabela_cache is not None:
        return _tabela_cache

    resp = requests.get(URL, headers=BROWSER_HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.content.decode("ISO-8859-1")

    m = re.search(r'id="chuva-limits".*?<tbody>(.*?)</tbody>', html, re.S)
    if m is None:
        raise ValueError("Tabela 'chuva-limits' não encontrada na página — layout pode ter mudado.")

    linhas = []
    for tr in re.findall(r"<tr>\s*(.*?)</tr>", m.group(1), re.S):
        celulas = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        celulas = [re.sub(r"<[^>]+>", "", c).strip() for c in celulas]
        if len(celulas) < 11 or not celulas[0]:
            continue
        linhas.append(
            {
                "fonte": celulas[0],
                "redec": celulas[1],
                "cidade": celulas[2],
                "estacao": celulas[3],
                "chuva_15min": _to_float(celulas[4]),
                "atualizado_em": _parse_data_hora(celulas[10]),
            }
        )

    _tabela_cache = linhas
    return linhas


class _BaseCbmerjPluviometroConnector(BaseConnector):
    """Compartilha o parsing; cada subclasse filtra sua própria "Fonte"."""

    fonte_filtro: str = ""
    website = URL
    description = "Pluviômetros via portal de sirenes do CEMADEN-RJ (hospedado no domínio do CBMERJ)."

    def fetch_stations(self) -> list[dict]:
        stations: dict[str, dict] = {}
        for linha in _fetch_tabela():
            if linha["fonte"] != self.fonte_filtro:
                continue
            centro = _centroide_municipio(linha["cidade"])
            if centro is None:
                logger.warning(
                    "%s: município '%s' sem centroide conhecido, estação '%s' ignorada.",
                    self.slug, linha["cidade"], linha["estacao"],
                )
                continue
            external_id = f"{_normaliza(linha['cidade'])}|{_normaliza(linha['estacao'])}"
            lat, lon = centro
            stations[external_id] = {
                "external_id": external_id,
                "name": linha["estacao"],
                "municipality": linha["cidade"],
                "station_type": Station.StationType.PLUVIOMETRICA,
                "status": Station.Status.ATIVA,
                "latitude": lat,
                "longitude": lon,
                "altitude_m": None,
                "raw_metadata": {
                    "redec": linha["redec"],
                    "fonte": linha["fonte"],
                    "coordenadas_aproximadas": True,
                },
            }
        return list(stations.values())

    def fetch_readings(self, stations: list[dict]) -> list[dict]:
        readings = []
        for linha in _fetch_tabela():
            if linha["fonte"] != self.fonte_filtro:
                continue
            if linha["chuva_15min"] is None or linha["atualizado_em"] is None:
                continue
            external_id = f"{_normaliza(linha['cidade'])}|{_normaliza(linha['estacao'])}"
            readings.append(
                {
                    "external_id": external_id,
                    "reading_type": Reading.ReadingType.CHUVA_MM,
                    "value": linha["chuva_15min"],
                    "timestamp": linha["atualizado_em"],
                    # raw_payload vai pra um JSONField — datetime não serializa.
                    "raw_payload": {**linha, "atualizado_em": linha["atualizado_em"].isoformat()},
                }
            )
        return readings


class CemadenRJConnector(_BaseCbmerjPluviometroConnector):
    slug = "cemaden_rj"
    name = "CEMADEN-RJ — Rede Própria (via portal de sirenes)"
    fonte_filtro = "CEMADEN RJ"


class CemadenMcticConnector(_BaseCbmerjPluviometroConnector):
    slug = "cemaden_mctic"
    name = "CEMADEN Nacional/MCTIC (via portal de sirenes do CEMADEN-RJ)"
    fonte_filtro = "CEMADEN MCTIC"
