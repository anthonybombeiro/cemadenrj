"""
Conector para a rede de estações "Alerta de Cheias" do INEA (Instituto
Estadual do Ambiente-RJ) — pluviômetros/linímetros (nível de rio),
combinando DUAS fontes públicas SEM login (dado pelo diretor da
CEMADEN-RJ em 2026-09-23, junto com um relato de tentativa anterior que
concluiu corretamente que "medições" e "cadastro das estações" são duas
fontes separadas — confirmado aqui):

  1. XML de leituras: `https://alertadecheias.inea.rj.gov.br/alertadecheias/dados.xml`
     (fallback por IP: `http://200.20.53.8/alertadecheias/dados.xml`, tentado
     só se o HTTPS falhar). 94 estações, mas SEM latitude/longitude — só
     `id` (código interno do INEA, formatos bem inconsistentes: pode ser
     numérico tipo "213042120" ou hex tipo "BE70A26C"), `nome`,
     `data_hora`, `dado_ultimo` (chuva no menor intervalo — bate com a
     coluna "15min" do mapa oficial), `chuva_1h`/`chuva_4h`/`chuva_24h`/
     `chuva_96h`/`chuva_30d` (acumulados prontos, não usados aqui — ver
     motivo em `_BaseCbmerjPluviometroConnector`/docs do projeto: a
     nossa própria agregação por Reading já cobre isso de forma
     consistente com as outras fontes), `nivel_rio` (nível do rio em
     metros — só numérico pra estações `tipo="Plu/Flu"`; pra `tipo="Plu"`
     vem o texto fixo "Estação pluviométrica" no lugar, sem nível).

  2. Página do mapa: `https://alertadecheias.inea.rj.gov.br/mapa.php` —
     SEM API/JSON por trás (diferente da Rede Salvar): as coordenadas de
     TODAS as estações (as 94, confirmado) vêm HARDCODED como chamadas
     `L.marker([lat, lon], ...)` dentro do HTML/JS inline da própria
     página. Cada marker tem nome da estação no popup e (pra 74 das 94)
     um link pra página individual (`alertadecheias/<código>.html`) —
     esse código individual é OUTRO esquema, diferente do `id` do XML
     (ex: XML `id="213042120"` vs link da mesma estação
     `alertadecheias/21304212020.html` — NÃO é o mesmo código, dá pra
     confirmar comparando dígito a dígito). Por isso a junção entre as
     duas fontes é feita pelo NOME normalizado da estação, não por
     código — testado e confirmado 100% de correspondência (94 de 94)
     entre as duas fontes por nome.

Sem município/bacia/rio na fonte (usuário já tinha percebido isso) — como
temos lat/lon EXATA da página do mapa, reconstruímos o município via
ponto-no-polígono contra a malha do IBGE que o projeto já usa
(`rj_municipios.geojson`, mesma fonte da coloração do mapa de risco),
em vez de tentar casar por nome (o nome da estação não é o nome do
município em ~30% dos casos). `raw_metadata["municipio_reconstruido"]`
fica True pra deixar isso rastreável.

`tipo="Plu"` (21 estações) → só chuva, sem nível de rio → tratamos como
`pluviometrica`. `tipo="Plu/Flu"` (73 estações) → chuva E nível de rio →
tratamos como `hidrologica` (é o propósito principal da rede "Alerta de
Cheias" do INEA), mas AINDA gera leitura de chuva também (não perde
dado, só a classificação do tipo de estação prioriza o nível).
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
import urllib3

from core.models import Reading, Station

from .base import BaseConnector

logger = logging.getLogger("ingestion")

# Ver comentário em _fetch_xml() sobre por que verify=False é necessário
# pra esse host específico — sem isso o urllib3 loga um warning a cada
# request, poluindo o log de ingestão à toa (já sabemos e documentamos).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URL_XML_HTTPS = "https://alertadecheias.inea.rj.gov.br/alertadecheias/dados.xml"
URL_XML_HTTP_IP = "http://200.20.53.8/alertadecheias/dados.xml"
URL_MAPA = "https://alertadecheias.inea.rj.gov.br/mapa.php"
TZ_RJ = ZoneInfo("America/Sao_Paulo")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
}

_GEOJSON_PATH = Path(__file__).resolve().parent.parent / "data" / "rj_municipios.geojson"
_geojson_cache: list[dict] | None = None

# Cache só pra evitar buscar a mesma fonte duas vezes dentro do MESMO
# processo (fetch_stations() e fetch_readings() usam as duas fontes) —
# mesma lógica de `_tabela_cache` em cemaden_rj_pluviometros.py.
_cache: dict[str, object] = {}


def _normaliza(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(sem_acento.upper().split())


def _to_float(valor) -> float | None:
    try:
        return float(str(valor).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _parse_data_hora(valor: str) -> dt.datetime | None:
    valor = (valor or "").strip()
    try:
        naive = dt.datetime.strptime(valor, "%d/%m/%Y %H:%M")
    except ValueError:
        return None
    return naive.replace(tzinfo=TZ_RJ).astimezone(dt.timezone.utc)


def _carrega_municipios() -> list[dict]:
    global _geojson_cache
    if _geojson_cache is None:
        data = json.loads(_GEOJSON_PATH.read_text(encoding="utf-8"))
        _geojson_cache = data["features"]
    return _geojson_cache


def _ponto_no_anel(lon: float, lat: float, anel: list[list[float]]) -> bool:
    """Ray casting padrão (PNPOLY) — anel é uma lista de [lon, lat]."""
    dentro = False
    n = len(anel)
    j = n - 1
    for i in range(n):
        xi, yi = anel[i][0], anel[i][1]
        xj, yj = anel[j][0], anel[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            dentro = not dentro
        j = i
    return dentro


def _municipio_de(lat: float, lon: float) -> str | None:
    """Ponto-no-polígono contra a malha de município do IBGE. Geometria é
    sempre MultiPolygon nesse arquivo (cada município pode ter ilhas)."""
    for feature in _carrega_municipios():
        geom = feature["geometry"]
        poligonos = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poligono in poligonos:
            anel_externo = poligono[0]
            if _ponto_no_anel(lon, lat, anel_externo):
                return feature["properties"]["nome"]
    return None


def _fetch_xml() -> str:
    if "xml" in _cache:
        return _cache["xml"]
    # verify=False DE PROPÓSITO, só pra esse host: o servidor do INEA
    # manda uma cadeia de certificado que o `certifi` do Python não
    # reconhece — "unable to get local issuer certificate", reproduzido
    # tanto local (Windows) quanto em produção (Linux/HostGator).
    # Confirmado que é problema da cadeia deles (não da nossa rede):
    # `curl` sem flag nenhuma funciona liso, porque usa a confiança do
    # SO (Windows/Linux trazem mais raízes que o certifi, provavelmente
    # cobrindo a cadeia ICP-Brasil — comum em .gov.br faltar um
    # intermediário no que o servidor manda). Fonte pública/só-leitura
    # (dado aberto de chuva/nível de rio, sem autenticação nem dado
    # sensível), então o risco de desabilitar a verificação aqui é
    # limitado — mesmo assim, escopado só pra esse fetch, não é global.
    try:
        resp = requests.get(URL_XML_HTTPS, headers=BROWSER_HEADERS, timeout=(10, 90), verify=False)
        resp.raise_for_status()
        texto = resp.content.decode("utf-8")
    except Exception as exc_https:  # noqa: BLE001
        logger.warning("INEA: HTTPS falhou (%s), tentando fallback por IP.", exc_https)
        try:
            resp = requests.get(URL_XML_HTTP_IP, headers=BROWSER_HEADERS, timeout=(10, 90))
            resp.raise_for_status()
            texto = resp.content.decode("utf-8")
        except Exception as exc_ip:  # noqa: BLE001
            raise RuntimeError(f"HTTPS falhou ({exc_https!r}) E fallback por IP falhou ({exc_ip!r})") from exc_ip
    _cache["xml"] = texto
    return texto


def _fetch_leituras() -> dict[str, dict]:
    """Retorna {nome_normalizado: {...}} a partir do XML de leituras."""
    xml = _fetch_xml()
    linhas: dict[str, dict] = {}
    for m in re.finditer(
        r'<estacao id="([^"]*)" tipo="([^"]*)">\s*'
        r"<nome>([^<]*)</nome>\s*"
        r"<data_hora>([^<]*)</data_hora>\s*"
        r"<dado_ultimo>([^<]*)</dado_ultimo>\s*"
        r"<chuva_1h>([^<]*)</chuva_1h>\s*"
        r"<chuva_4h>([^<]*)</chuva_4h>\s*"
        r"<chuva_24h>([^<]*)</chuva_24h>\s*"
        r"<chuva_96h>([^<]*)</chuva_96h>\s*"
        r"<chuva_30d>([^<]*)</chuva_30d>\s*"
        r"<nivel_rio>([^<]*)</nivel_rio>",
        xml,
    ):
        codigo, tipo, nome, data_hora, dado_ultimo, chuva_1h, *_resto, nivel_rio = m.groups()
        nome_norm = _normaliza(nome)
        linhas[nome_norm] = {
            "codigo": codigo,
            "tipo": tipo,
            "nome": nome.strip(),
            "data_hora": _parse_data_hora(data_hora),
            "chuva_mm": _to_float(dado_ultimo),
            "nivel_m": _to_float(nivel_rio),
        }
    return linhas


def _fetch_mapa() -> dict[str, dict]:
    """Retorna {nome_normalizado: {"lat":..., "lon":...}} a partir dos
    L.marker(...) embutidos no HTML/JS de mapa.php."""
    if "mapa" in _cache:
        return _cache["mapa"]
    resp = requests.get(URL_MAPA, headers=BROWSER_HEADERS, timeout=30, verify=False)  # ver _fetch_xml() sobre o verify=False
    resp.raise_for_status()
    # .content.decode("utf-8") explícito, NÃO resp.text: o servidor manda
    # Content-Type: text/html sem declarar charset, então o requests cai
    # no default do HTTP (ISO-8859-1) mesmo o corpo sendo UTF-8 de
    # verdade — resp.text vinha com "Estação" virando mojibake
    # ("EstaÃ§Ã£o"), quebrando o regex de nome silenciosamente (0
    # estações casadas, sem erro nenhum). Mesmo motivo no XML acima.
    html = resp.content.decode("utf-8")
    estacoes: dict[str, dict] = {}
    for bloco in re.split(r"(?=L\.marker\()", html):
        if not bloco.startswith("L.marker("):
            continue
        m_latlon = re.match(r"L\.marker\(\['([\-0-9.]+)', '([\-0-9.]+)'\]", bloco)
        m_nome = re.search(r"Estação ([^<]+)</th>", bloco)
        if not (m_latlon and m_nome):
            continue
        nome_norm = _normaliza(m_nome.group(1))
        estacoes[nome_norm] = {"lat": float(m_latlon.group(1)), "lon": float(m_latlon.group(2))}
    _cache["mapa"] = estacoes
    return estacoes


class INEAConnector(BaseConnector):
    slug = "inea"
    name = "INEA — Alerta de Cheias"
    website = URL_MAPA
    description = (
        "Pluviômetros/linímetros do INEA (Instituto Estadual do Ambiente-RJ), rede de Alerta de Cheias — "
        "leituras via XML público + coordenadas via a página do mapa oficial (sem API pública unificada)."
    )

    def fetch_stations(self) -> list[dict]:
        leituras = _fetch_leituras()
        mapa = _fetch_mapa()
        stations = []
        for nome_norm, linha in leituras.items():
            geo = mapa.get(nome_norm)
            if geo is None:
                logger.warning(
                    "INEA: estação '%s' (código %s) tem leitura no XML mas não achou coordenada no mapa — ignorada.",
                    linha["nome"], linha["codigo"],
                )
                continue
            municipio = _municipio_de(geo["lat"], geo["lon"]) or ""
            eh_hidrologica = linha["tipo"] == "Plu/Flu"
            stations.append(
                {
                    "external_id": nome_norm,  # ver docstring: os 2 esquemas de código não batem entre si nem são estáveis o bastante — nome normalizado é a chave confiável aqui
                    "name": linha["nome"],
                    "municipality": municipio,
                    "station_type": Station.StationType.HIDROLOGICA if eh_hidrologica else Station.StationType.PLUVIOMETRICA,
                    "status": Station.Status.ATIVA,
                    "latitude": geo["lat"],
                    "longitude": geo["lon"],
                    "altitude_m": None,
                    "raw_metadata": {
                        "codigo_inea": linha["codigo"],
                        "tipo_inea": linha["tipo"],
                        "municipio_reconstruido": True,
                    },
                }
            )
        return stations

    def fetch_readings(self, stations: list[dict]) -> list[dict]:
        leituras = _fetch_leituras()
        readings = []
        for nome_norm, linha in leituras.items():
            if linha["data_hora"] is None:
                continue
            if linha["chuva_mm"] is not None:
                readings.append(
                    {
                        "external_id": nome_norm,
                        "reading_type": Reading.ReadingType.CHUVA_MM,
                        "value": linha["chuva_mm"],
                        "timestamp": linha["data_hora"],
                        "raw_payload": {**linha, "data_hora": linha["data_hora"].isoformat()},
                    }
                )
            if linha["tipo"] == "Plu/Flu" and linha["nivel_m"] is not None:
                readings.append(
                    {
                        "external_id": nome_norm,
                        "reading_type": Reading.ReadingType.NIVEL_M,
                        "value": linha["nivel_m"],
                        "timestamp": linha["data_hora"],
                        "raw_payload": {**linha, "data_hora": linha["data_hora"].isoformat()},
                    }
                )
        return readings
