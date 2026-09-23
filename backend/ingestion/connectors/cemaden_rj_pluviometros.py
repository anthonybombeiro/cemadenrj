"""
Conectores para duas fontes distintas de pluviômetros:

1. `CemadenRJConnector` — página pública do Sistema de Alerta e Alarme
   Sonoro (rede de sirenes do estado), hospedado no domínio do CBMERJ mas
   operado pelo CEMADEN-RJ (confirmado pelo usuário — diretor do
   CEMADEN-RJ — em setembro/2026: o CBMERJ só empresta domínio/servidor,
   ambos são órgãos da mesma Secretaria de Estado de Defesa Civil).
   `ConsultaPluviometros?cmd=dadosPluviometros` → só CEMADEN-RJ (~85
   estações, rede PRÓPRIA do estado — o pedido original deste projeto).
   Colunas: Redec, Cidade, Estação, 3 Min, 15 Min, 1 Hora, 4 Horas,
   12 Horas, 24 Horas, 48 Horas, 72 Horas, 96 Horas, 1 Mês, Data e Hora.
   Sem código de estação nem lat/lon — aproximamos pelo centroide do
   município (ver `_centroide_municipio`). Página HTML pública, SEM
   login.

2. `CemadenMcticConnector` — API JSON pública e oficial do próprio
   CEMADEN nacional (`resources.cemaden.gov.br`), achada investigando de
   onde o portal de sirenes do CEMADEN-RJ tira o dado do CEMADEN
   nacional (pedido do usuário, setembro/2026). O portal de sirenes tem
   uma página dedicada (`ConsultaPluviometros?cmd=dadosPluviometrosCemaden`)
   que faz scraping de HTML do mesmo dado — mas achamos a fonte
   verdadeira ao ler o JS da página pública
   `resources.cemaden.gov.br/graficos/interativo/grafico_CEMADEN.php?uf=RJ`
   (usada pelo próprio CEMADEN nacional pra exibir o gráfico interativo
   por UF): ela chama `getJson2.php?uf=RJ`, que é JSON puro, público, sem
   login, MELHOR que a página do CBMERJ nos 3 aspectos que importam:
     - 395 estações (vs. 247 na página raspada) — mais completo;
     - `codibge` = código IBGE exato do município (não precisa casar por
       nome, elimina risco de erro de acentuação/grafia);
     - `idestacao` = ID numérico único e estável do CEMADEN nacional —
       usado direto como `external_id`, sem precisar inventar chave.
   `tipoestacao` classifica o tipo de PCD (Plataforma de Coleta de
   Dados): 1 = pluviométrica (a maioria, ~356 das 395 estações de RJ),
   10 = geotécnica (nomes com sufixo "GEO"), 3 = hidrológica/nível de rio
   (nomes tipo "Rio X"), 4 = poucas, sem valor — só usamos `tipoestacao
   == 1` aqui, que é o que interessa pra chuva.

   O cabeçalho da tabela da própria página do CEMADEN nacional diz
   "Data (Horário UTC)" — `datahoraUltimovalor` já vem em UTC, ao
   contrário das páginas do portal de sirenes (que são hora local de
   Brasília). Formato: "DD/MM/AA HH:MM" (ano com 2 dígitos, sem
   segundos).

Ambas SEM latitude/longitude exata — aproximamos com o centroide do
município (`ingestion/data/rj_municipios_centroides.json`, calculado a
partir da malha do IBGE, com chave dupla: nome normalizado E código IBGE
— ver frontend/src/lib/geo.ts pro equivalente do lado do frontend).
`raw_metadata["coordenadas_aproximadas"]` fica True pra deixar isso
rastreável — não é a posição exata do pluviômetro, é o centro do
município. Dá pra estação aparecer no mapa, mas não usar isso pra nada
que precise de precisão de local.

O valor que guardamos como `chuva_mm` é sempre o da MENOR janela
disponível em cada fonte ("15 Min" pro CEMADEN-RJ via CBMERJ,
`ultimovalor` pro CEMADEN nacional via `getJson2.php` — telemetria de
PCD costuma reportar a cada ~10-15min, então tratamos como chuva NA
JANELA daquela leitura, tipo "balde", igual Alerta Rio/INMET — ver
`PRECIPITACAO_BUCKET_SOURCES` em `api/views.py`). As janelas maiores que
as APIs já entregam prontas (1h/6h/12h/24h/48h/72h/96h, ...) NÃO são
usadas diretamente — preferimos deixar nosso próprio endpoint de
acumulado (que soma os valores da menor janela ao longo do tempo)
calcular do jeito consistente com as outras fontes, mesmo que isso
signifique um "aquecimento" de até 4 dias pra 96h ficar completo.
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

# API JSON pública e oficial do CEMADEN nacional (não é mais a página
# raspada do portal do CBMERJ — ver docstring do módulo).
URL_CEMADEN_NACIONAL_JSON = "https://resources.cemaden.gov.br/graficos/interativo/getJson2.php?uf=RJ"
TIPOESTACAO_PLUVIOMETRICA = 1

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


def _centroide_por_codibge(codibge: int | str) -> tuple[float, float] | None:
    """Mesmo arquivo de centroides do `_centroide_municipio`, mas
    buscando pela chave de código IBGE (`codarea`) em vez do nome — o
    JSON do CEMADEN nacional já vem com o código exato, então evitamos
    o risco de nome/acentuação não bater."""
    global _centroides_cache
    if _centroides_cache is None:
        _centroides_cache = json.loads(_CENTROIDES_PATH.read_text(encoding="utf-8"))
    par = _centroides_cache.get(str(codibge))
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


def _parse_data_hora_utc(valor: str) -> dt.datetime | None:
    """Formato "DD/MM/AA HH:MM" (ano 2 dígitos, sem segundos) — a própria
    tabela do CEMADEN nacional rotula essa coluna como "Data (Horário
    UTC)", ao contrário das páginas do portal de sirenes (hora local),
    então aqui NÃO localizamos pra America/Sao_Paulo antes de converter."""
    valor = (valor or "").strip()
    try:
        naive = dt.datetime.strptime(valor, "%d/%m/%y %H:%M")
    except ValueError:
        return None
    return naive.replace(tzinfo=dt.timezone.utc)


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


def _fetch_cemaden_nacional_json() -> list[dict]:
    """Busca `getJson2.php?uf=RJ` e filtra só as PCDs pluviométricas
    (`tipoestacao == 1`) — as outras (geotécnica/hidrológica) não têm
    semântica de chuva."""
    if URL_CEMADEN_NACIONAL_JSON in _tabela_cache:
        return _tabela_cache[URL_CEMADEN_NACIONAL_JSON]
    resp = requests.get(URL_CEMADEN_NACIONAL_JSON, headers=BROWSER_HEADERS, timeout=30)
    resp.raise_for_status()
    registros = resp.json()
    linhas = [r for r in registros if r.get("tipoestacao") == TIPOESTACAO_PLUVIOMETRICA]
    _tabela_cache[URL_CEMADEN_NACIONAL_JSON] = linhas
    return linhas


class CemadenRJConnector(BaseConnector):
    """Rede PRÓPRIA de pluviômetros da CEMADEN-RJ, via página HTML pública
    do portal de sirenes (hospedado no domínio do CBMERJ)."""

    slug = "cemaden_rj"
    name = "CEMADEN-RJ — Rede Própria (via portal de sirenes)"
    website = URL_CEMADEN_RJ
    description = "Pluviômetros da rede própria da CEMADEN-RJ, via portal de sirenes (domínio do CBMERJ)."

    def _external_id(self, linha: dict) -> str:
        # Sem código oficial nessa página — chave sintética estável.
        return f"{_normaliza(linha['cidade'])}|{_normaliza(linha['estacao'])}"

    def fetch_stations(self) -> list[dict]:
        stations: dict[str, dict] = {}
        for linha in _fetch_tabela_cemaden_rj():
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
        for linha in _fetch_tabela_cemaden_rj():
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


class CemadenMcticConnector(BaseConnector):
    """CEMADEN Nacional/MCTIC — via API JSON pública e oficial
    (`resources.cemaden.gov.br/graficos/interativo/getJson2.php`), não
    mais a página raspada do portal de sirenes. Ver docstring do módulo
    pra como essa fonte foi encontrada e por que é melhor."""

    slug = "cemaden_mctic"
    name = "CEMADEN Nacional/MCTIC"
    website = "https://resources.cemaden.gov.br/graficos/interativo/grafico_CEMADEN.php?uf=RJ"
    description = "Pluviômetros do CEMADEN nacional em RJ, via API JSON pública oficial (getJson2.php)."

    def _external_id(self, registro: dict) -> str:
        # idestacao é o ID numérico único e estável do CEMADEN nacional.
        return str(registro["idestacao"])

    def fetch_stations(self) -> list[dict]:
        stations: dict[str, dict] = {}
        for registro in _fetch_cemaden_nacional_json():
            codibge = registro.get("codibge")
            centro = _centroide_por_codibge(codibge) if codibge is not None else None
            if centro is None:
                logger.warning(
                    "%s: codibge %r sem centroide conhecido, estação '%s' (id %s) ignorada.",
                    self.slug, codibge, registro.get("nomeestacao"), registro.get("idestacao"),
                )
                continue
            external_id = self._external_id(registro)
            lat, lon = centro
            stations[external_id] = {
                "external_id": external_id,
                "name": registro.get("nomeestacao") or f"PCD {registro['idestacao']}",
                "municipality": registro.get("cidade", ""),
                "station_type": Station.StationType.PLUVIOMETRICA,
                "status": Station.Status.ATIVA,
                "latitude": lat,
                "longitude": lon,
                "altitude_m": None,
                "raw_metadata": {
                    "idestacao": registro["idestacao"],
                    "codibge": codibge,
                    "uf": registro.get("uf"),
                    "coordenadas_aproximadas": True,
                },
            }
        return list(stations.values())

    def fetch_readings(self, stations: list[dict]) -> list[dict]:
        readings = []
        for registro in _fetch_cemaden_nacional_json():
            valor = registro.get("ultimovalor")
            timestamp = _parse_data_hora_utc(registro.get("datahoraUltimovalor", ""))
            if valor is None or timestamp is None:
                continue
            readings.append(
                {
                    "external_id": self._external_id(registro),
                    "reading_type": Reading.ReadingType.CHUVA_MM,
                    "value": float(valor),
                    "timestamp": timestamp,
                    # raw_payload vai pra um JSONField — já é tudo str/int/float aqui.
                    "raw_payload": registro,
                }
            )
        return readings
