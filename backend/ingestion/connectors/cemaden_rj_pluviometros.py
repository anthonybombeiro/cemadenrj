"""
Conectores para as páginas públicas de pluviômetros do Sistema de Alerta e
Alarme Sonoro (rede de sirenes do estado), hospedado no domínio do CBMERJ
mas operado pelo CEMADEN-RJ (confirmado pelo usuário — diretor do
CEMADEN-RJ — em setembro/2026: o CBMERJ só empresta domínio/servidor,
ambos são órgãos da mesma Secretaria de Estado de Defesa Civil).

Existem várias páginas com `cmd=` diferentes, cada uma dedicada a UMA
fonte (testado sistematicamente em setembro/2026 — nenhuma delas revela
de onde o CEMADEN-RJ tira o dado do CEMADEN nacional, mas a página
dedicada tem uma coluna que a combinada não tem, ver abaixo):

  - `ConsultaPluviometros?cmd=dadosPluviometros`
    → só CEMADEN-RJ (~85 estações, rede PRÓPRIA do estado — nunca
    tínhamos acesso direto a isso antes, é o pedido original deste
    projeto). Colunas: Redec, Cidade, Estação, 3 Min, 15 Min, 1 Hora,
    4 Horas, 12 Horas, 24 Horas, 48 Horas, 72 Horas, 96 Horas, 1 Mês,
    Data e Hora. Sem código de estação.
  - `ConsultaPluviometros?cmd=dadosPluviometrosCemaden`
    → só CEMADEN Nacional/MCTIC (~247 estações — mesma rede do
    `cemaden_nacional.py` antigo, cujo endpoint documentado está morto há
    meses; esse canal funciona de verdade). Colunas: Redec, Cidade, Nome
    Estação, **Codigo Estação** (ex: "330580216A" — formato oficial do
    CEMADEN nacional, UF+município+sequencial+tipo), 15 Min, 1 Hora,
    4 Horas, 24 Horas, 96 Horas, 1 Mês, Data e Hora. Usamos o código
    oficial como `external_id` — bem melhor que inventar uma chave.
  - `ConsultaPluviometros?cmd=dadosPluviometrosTotal`
    → as duas acima JUNTAS + ~30 estações de Niterói, com uma coluna
    "Fonte" a mais pra distinguir. Não usamos mais essa (preferimos as
    dedicadas, que têm mais detalhe); Niterói tem API própria com
    lat/lon exata, usada em `niteroi.py`.

Todas são páginas HTML públicas, SEM login (testado direto, sem
sessão/cookie).

Sem latitude/longitude nas tabelas — só Redec/Cidade/Estação. Aproximamos
com o centroide do município (`ingestion/data/rj_municipios_centroides.json`,
calculado a partir da malha do IBGE — ver frontend/src/lib/geo.ts pro
equivalente do lado do frontend). `raw_metadata["coordenadas_aproximadas"]`
fica True pra deixar isso rastreável — não é a posição exata do
pluviômetro, é o centro do município. Dá pra estação aparecer no mapa,
mas não usar isso pra nada que precise de precisão de local.

"15 Min" é o valor que guardamos como `chuva_mm` — é chuva NA janela dos
últimos 15 min (tipo "balde", igual Alerta Rio/INMET — ver
`PRECIPITACAO_BUCKET_SOURCES` em `api/views.py`). As janelas maiores que
as tabelas já entregam prontas (1h/4h/24h/96h/1mês, ...) NÃO são usadas
diretamente — preferimos deixar nosso próprio endpoint de acumulado (que
soma os "15 Min" ao longo do tempo) calcular do jeito consistente com as
outras fontes, mesmo que isso signifique um "aquecimento" de até 4 dias
pra 96h ficar completo.
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

BASE_URL = "http://sirene.cbmerj.rj.gov.br:8080/sirenesestadorj/ConsultaPluviometros"
URL_CEMADEN_RJ = f"{BASE_URL}?cmd=dadosPluviometros"
URL_CEMADEN_MCTIC = f"{BASE_URL}?cmd=dadosPluviometrosCemaden"
TZ_RJ = ZoneInfo("America/Sao_Paulo")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
}

_CENTROIDES_PATH = Path(__file__).resolve().parent.parent / "data" / "rj_municipios_centroides.json"
_centroides_cache: dict[str, list[float]] | None = None

# Cache só pra evitar buscar a mesma página HTML duas vezes dentro do
# MESMO processo — fetch_stations() e fetch_readings() são chamados em
# sequência por BaseConnector.run() e parseiam a mesma tabela. Não
# sobrevive entre requisições diferentes (cada ingest roda num processo
# CGI novo em produção), então não precisa de expiração por tempo.
_tabela_cache: dict[str, list[dict]] = {}


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


def _baixar_tabela(url: str) -> str:
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.content.decode("ISO-8859-1")
    m = re.search(r'id="chuva-limits".*?<tbody>(.*?)</tbody>', html, re.S)
    if m is None:
        raise ValueError(f"Tabela 'chuva-limits' não encontrada em {url} — layout pode ter mudado.")
    return m.group(1)


def _linhas_cruas(url: str) -> list[list[str]]:
    corpo = _baixar_tabela(url)
    linhas = []
    for tr in re.findall(r"<tr>\s*(.*?)</tr>", corpo, re.S):
        celulas = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        celulas = [re.sub(r"<[^>]+>", "", c).strip() for c in celulas]
        if celulas and celulas[0]:
            linhas.append(celulas)
    return linhas


def _fetch_tabela_cemaden_rj() -> list[dict]:
    """Colunas: Redec(0) Cidade(1) Estação(2) 3Min(3) 15Min(4) 1Hora(5) ..."""
    if URL_CEMADEN_RJ in _tabela_cache:
        return _tabela_cache[URL_CEMADEN_RJ]
    linhas = []
    for c in _linhas_cruas(URL_CEMADEN_RJ):
        if len(c) < 14:
            continue
        linhas.append(
            {
                "redec": c[0],
                "cidade": c[1],
                "estacao": c[2],
                "codigo": None,
                "chuva_15min": _to_float(c[4]),
                "atualizado_em": _parse_data_hora(c[13]),
            }
        )
    _tabela_cache[URL_CEMADEN_RJ] = linhas
    return linhas


def _fetch_tabela_cemaden_mctic() -> list[dict]:
    """Colunas: Redec(0) Cidade(1) NomeEstação(2) CodigoEstação(3) 15Min(4) ..."""
    if URL_CEMADEN_MCTIC in _tabela_cache:
        return _tabela_cache[URL_CEMADEN_MCTIC]
    linhas = []
    for c in _linhas_cruas(URL_CEMADEN_MCTIC):
        if len(c) < 11:
            continue
        linhas.append(
            {
                "redec": c[0],
                "cidade": c[1],
                "estacao": c[2],
                "codigo": c[3],
                "chuva_15min": _to_float(c[4]),
                "atualizado_em": _parse_data_hora(c[10]),
            }
        )
    _tabela_cache[URL_CEMADEN_MCTIC] = linhas
    return linhas


class _BaseCbmerjPluviometroConnector(BaseConnector):
    """Compartilha a montagem de estação/leitura; cada subclasse só define
    de onde vêm as linhas e como calcular o external_id."""

    website = BASE_URL
    description = "Pluviômetros via portal de sirenes do CEMADEN-RJ (hospedado no domínio do CBMERJ)."

    def _fetch_linhas(self) -> list[dict]:
        raise NotImplementedError

    def _external_id(self, linha: dict) -> str:
        raise NotImplementedError

    def fetch_stations(self) -> list[dict]:
        stations: dict[str, dict] = {}
        for linha in self._fetch_linhas():
            centro = _centroide_municipio(linha["cidade"])
            if centro is None:
                logger.warning(
                    "%s: município '%s' sem centroide conhecido, estação '%s' ignorada.",
                    self.slug, linha["cidade"], linha["estacao"],
                )
                continue
            external_id = self._external_id(linha)
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
                    "codigo_estacao": linha["codigo"],
                    "coordenadas_aproximadas": True,
                },
            }
        return list(stations.values())

    def fetch_readings(self, stations: list[dict]) -> list[dict]:
        readings = []
        for linha in self._fetch_linhas():
            if linha["chuva_15min"] is None or linha["atualizado_em"] is None:
                continue
            readings.append(
                {
                    "external_id": self._external_id(linha),
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

    def _fetch_linhas(self) -> list[dict]:
        return _fetch_tabela_cemaden_rj()

    def _external_id(self, linha: dict) -> str:
        # Sem código oficial nessa página — chave sintética estável.
        return f"{_normaliza(linha['cidade'])}|{_normaliza(linha['estacao'])}"


class CemadenMcticConnector(_BaseCbmerjPluviometroConnector):
    slug = "cemaden_mctic"
    name = "CEMADEN Nacional/MCTIC (via portal de sirenes do CEMADEN-RJ)"

    def _fetch_linhas(self) -> list[dict]:
        return _fetch_tabela_cemaden_mctic()

    def _external_id(self, linha: dict) -> str:
        # Código oficial do CEMADEN nacional (ex: "330580216A") — usa
        # direto, é bem mais estável que inventar uma chave por nome.
        return linha["codigo"] or f"{_normaliza(linha['cidade'])}|{_normaliza(linha['estacao'])}"
