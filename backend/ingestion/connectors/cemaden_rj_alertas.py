"""
Alertas oficiais de risco da Defesa Civil-RJ (CEMADEN-RJ/SEDEC) — não são
dados de estação (chuva/temperatura/...), são a classificação de risco por
REDEC ou por município que hoje só existe no painel legado (GridLab) em
`https://painelcemadenrj.defesacivil.rj.gov.br`.

Achado em setembro/2026: existe uma API pública, SEM login, feita pela
própria Defesa Civil-RJ para integração com Power BI, em
`/integracao/envia/cemaden/`. Ver docs/fontes-de-dados.md para o
levantamento completo dos 8 endpoints. Usamos 4 deles aqui — um por
camada de alerta (hidrológico, geológico, severidade meteorológica,
incêndio florestal):

  - atualizacao_hidro.php           → hidrológico, por REDEC
  - atualizacao_geo.php             → geológico, por REDEC
  - atualizacao_municipio_geo.php   → geológico, por município (sempre os 92)
  - atualizacao_municipio_hidro.php → hidrológico, por município. O usuário
    (que opera o sistema de verdade) descreveu que essa granularidade
    "passa a existir a partir do risco Alto" — mas quando o fetch
    finalmente funcionou (ver instabilidade abaixo), a resposta trouxe os
    92 municípios com níveis variados (inclusive "moderado"), igual ao
    geológico. Pode ser que a regra operacional de quando isso é
    RELEVANTE seja a partir de Alto, mesmo a fonte sempre devolvendo tudo
    — deixamos os 92 disponíveis de qualquer forma, não faz mal mostrar a
    mais.
    ATENÇÃO — esse endpoint específico é instável NO SERVIDOR DELES:
    testado repetidas vezes (com e sem headers de navegador, com curl e
    com requests) e ele devolve 500 Internal Server Error na maioria das
    tentativas e 200 com dado real ocasionalmente (~1 em 4), sem relação
    com headers — mesmo request idêntico alterna entre os dois. O mapa
    público (`/monitoramento/v2/mapa/`, confirmado com print do usuário
    mostrando município com cores diferentes dentro de uma mesma REDEC)
    prova que o dado por-município existe e é usado ao vivo por eles; só
    esse endpoint específico de integração é que está instável.
    `_stream_rows` tenta de novo algumas vezes antes de desistir (ver
    `_MAX_TENTATIVAS`). Mesmo assim pode falhar; `sync()` trata isso como
    "sem dado agora" (loga o erro, não deleta nada) em vez de deixar a
    exceção propagar e derrubar a
    sincronização dos outros 3 tipos de alerta. E como só listamos quem
    está atualmente acima do limiar, `sync()` também apaga registro de
    município que sumiu da resposta (senão um "ALTO" antigo ficaria preso
    pra sempre depois do risco baixar).
  - redec_meteoro.php?action=1      → severidade meteorológica, por REDEC
  - redec_meteoro.php?action=2      → incêndio florestal, por REDEC

Não existe granularidade municipal pra meteorológico/incêndio na fonte.

IMPORTANTE sobre tamanho: esses endpoints devolvem o HISTÓRICO COMPLETO de
alterações, não só o estado atual — o de geológico por município já passou
de 40MB num teste real. Baixar isso inteiro pra memória e só depois separar
"qual é o mais recente" quebraria em hospedagem compartilhada com RAM
limitada. Por isso o parsing é feito em streaming (HTMLParser processando
pedaço por pedaço da resposta, nunca o HTML inteiro de uma vez) e mantém só
a "melhor" linha por chave (REDEC ou Município) enquanto lê — memória
proporcional ao número de REDECs/municípios (dezenas), não ao número de
linhas do histórico (podem ser dezenas de milhares).
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger("ingestion")

BASE_URL = "https://painelcemadenrj.defesacivil.rj.gov.br/integracao/envia/cemaden"
TZ_RJ = ZoneInfo("America/Sao_Paulo")

REDECS = [
    "BAIXADA FLUMINENSE",
    "BAIXADA LITORÂNEA",
    "CAPITAL",
    "COSTA VERDE",
    "METROPOLITANA",
    "NORTE",
    "NOROESTE",
    "SERRANA I",
    "SERRANA II",
    "SUL I",
    "SUL II",
]

_RISCO_MAP = {
    "MUITO BAIXO": "muito_baixo",
    "BAIXO": "baixo",
    "MODERADO": "moderado",
    "ALTO": "alto",
    "MUITO ALTO": "muito_alto",
}


def _normaliza_risco(valor: str) -> str | None:
    return _RISCO_MAP.get((valor or "").strip().upper())


def _normaliza_redec(valor: str) -> str:
    # A fonte não é consistente: `atualizacao_municipio_geo.php` manda
    # "BAIXADA  LITORÂNEA" com DOIS espaços, enquanto `redec_meteoro.php`
    # e os outros endpoints mandam um só — sem isso, o nome de REDEC vindo
    # de um endpoint não bate com o de outro (achado comparando os dois
    # conjuntos direto no banco), quebrando qualquer código que precise
    # cruzar REDEC entre tipos de alerta diferentes (ex: colorir município
    # pelo risco da REDEC quando o tipo não tem dado municipal).
    return " ".join((valor or "").split())


def _parse_data_hora(data_str: str, hora_str: str) -> dt.datetime | None:
    data_str = (data_str or "").strip()
    hora_str = (hora_str or "").strip() or "00:00:00"
    if not data_str:
        return None
    try:
        naive = dt.datetime.strptime(f"{data_str} {hora_str}", "%d/%m/%Y %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=TZ_RJ).astimezone(dt.timezone.utc)


def _to_int(valor: str) -> int:
    try:
        return int((valor or "").strip())
    except ValueError:
        return 0


class _TableRowParser(HTMLParser):
    """Extrai linhas de `<tbody><tr><td>...</td></tr></tbody>` em streaming,
    chamando `on_row(lista_de_celulas)` a cada `</tr>` fechada. Ignora linhas
    de `<thead>`/`<tfoot>` (que só têm `<th>`, nunca `<td>`, nesses arquivos)."""

    def __init__(self, on_row):
        super().__init__()
        self._on_row = on_row
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._current_row = []
        elif tag == "td":
            self._current_cell = []

    def handle_endtag(self, tag):
        if tag == "td" and self._current_cell is not None and self._current_row is not None:
            self._current_row.append("".join(self._current_cell).strip())
            self._current_cell = None
        elif tag == "tr":
            if self._current_row:
                self._on_row(self._current_row)
            self._current_row = None

    def handle_data(self, data):
        if self._current_cell is not None:
            self._current_cell.append(data)


_HEADERS = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

# `atualizacao_municipio_hidro.php` especificamente é instável no servidor
# deles — 500 na maioria das tentativas, 200 com dado real de vez em quando,
# não relacionado a headers nem a ter ou não município em risco alto (ver
# docstring do módulo). Tenta de novo antes de desistir.
_MAX_TENTATIVAS = 10
_ESPERA_ENTRE_TENTATIVAS_S = 1


def _stream_rows(url: str, on_row) -> None:
    ultimo_erro: Exception | None = None
    for tentativa in range(1, _MAX_TENTATIVAS + 1):
        parser = _TableRowParser(on_row)
        try:
            with requests.get(url, headers=_HEADERS, timeout=(10, 60), stream=True) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=1 << 16, decode_unicode=True):
                    if chunk:
                        parser.feed(chunk)
            parser.close()
            return
        except requests.exceptions.HTTPError as exc:
            ultimo_erro = exc
            status = exc.response.status_code if exc.response is not None else None
            if status is not None and status < 500:
                raise  # erro do lado de cá (4xx) — tentar de novo não ajuda
            logger.warning("Tentativa %d/%d falhou para %s: %s", tentativa, _MAX_TENTATIVAS, url, exc)
            if tentativa < _MAX_TENTATIVAS:
                time.sleep(_ESPERA_ENTRE_TENTATIVAS_S)
    assert ultimo_erro is not None
    raise ultimo_erro


@dataclass
class AlertSyncResult:
    upserted: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return f"alertas atualizados: {self.upserted} | erros: {len(self.errors)}"


def _fetch_redec_log(tipo: str, url: str) -> dict[str, dict]:
    """hidro/geo por REDEC: colunas Aviso, Redec, Mensagem, Atualização,
    Risco Atual, Data, Hora, Ano, Fonte. Mantém só a linha mais recente
    (maior Mensagem, depois maior Atualização) por Redec."""
    melhor: dict[str, tuple[int, int, list[str]]] = {}

    def on_row(cells: list[str]) -> None:
        if len(cells) < 9:
            return
        _aviso, redec, mensagem, atualizacao, *_resto = cells
        redec = _normaliza_redec(redec)
        chave_ordem = (_to_int(mensagem), _to_int(atualizacao))
        atual = melhor.get(redec)
        if atual is None or chave_ordem > atual[:2]:
            melhor[redec] = (*chave_ordem, cells)

    _stream_rows(url, on_row)

    resultado = {}
    for redec, (_num, _upd, cells) in melhor.items():
        _aviso, _redec, mensagem, _atualizacao, risco_atual, data, hora, _ano, fonte = cells
        risco = _normaliza_risco(risco_atual)
        if risco is None:
            continue
        resultado[redec] = {
            "redec": redec,
            "risco": risco,
            "numero_externo": mensagem,
            "atualizado_em": _parse_data_hora(data, hora),
            "fonte": fonte,
            "raw_payload": {"cells": cells},
        }
    return resultado


def _fetch_municipio(url: str) -> dict[str, dict]:
    """Por município: colunas Aviso, Redec, Municipio, Mensagem,
    Atualização, Risco, Data Criação, Hora Criação, Ano Criação,
    Responsável Criação, Data Atualização, Hora Atualização, Ano
    Atualização, Responsável Atualização, Fonte. Usada tanto por geológico
    (sempre populada) quanto por hidrológico (só tem linhas quando algum
    município chega a "ALTO" — pode voltar vazia/sem `<table>` nenhuma, o
    que o `_stream_rows` trata normalmente, sem erro: `on_row` simplesmente
    nunca é chamado e o resultado fica `{}`)."""
    melhor: dict[str, tuple[int, int, list[str]]] = {}

    def on_row(cells: list[str]) -> None:
        if len(cells) < 15:
            return
        _aviso, _redec, municipio, mensagem, atualizacao, *_resto = cells
        chave_ordem = (_to_int(mensagem), _to_int(atualizacao))
        atual = melhor.get(municipio)
        if atual is None or chave_ordem > atual[:2]:
            melhor[municipio] = (*chave_ordem, cells)

    _stream_rows(url, on_row)

    resultado = {}
    for municipio, (_num, _upd, cells) in melhor.items():
        (
            _aviso, redec, _municipio, mensagem, _atualizacao, risco,
            data_c, hora_c, _ano_c, resp_c,
            data_a, hora_a, _ano_a, resp_a,
            fonte,
        ) = cells
        redec = _normaliza_redec(redec)
        risco_norm = _normaliza_risco(risco)
        if risco_norm is None:
            continue
        atualizado_em = _parse_data_hora(data_a, hora_a) or _parse_data_hora(data_c, hora_c)
        resultado[municipio] = {
            "redec": redec,
            "municipio": municipio,
            "risco": risco_norm,
            "numero_externo": mensagem,
            "responsavel": resp_a or resp_c,
            "criado_em": _parse_data_hora(data_c, hora_c),
            "atualizado_em": atualizado_em,
            "fonte": fonte,
            "raw_payload": {"cells": cells},
        }
    return resultado


def _fetch_redec_bulletin(action: int) -> dict[str, dict]:
    """severidade meteorológica / incêndio florestal: 1 linha por boletim,
    1 coluna por REDEC (ordem fixa de REDECS acima). Usa o boletim com
    "Ativo"="SIM"; se nenhum estiver marcado, cai pro de maior Nº."""
    melhor: list[str] | None = None
    melhor_num = -1
    melhor_ativo = False

    def on_row(cells: list[str]) -> None:
        nonlocal melhor, melhor_num, melhor_ativo
        if len(cells) < 4 + len(REDECS):
            return
        numero = _to_int(cells[0])
        ativo = cells[2].strip().upper() == "SIM"
        if ativo and not melhor_ativo:
            melhor, melhor_num, melhor_ativo = cells, numero, True
        elif ativo == melhor_ativo and numero > melhor_num:
            melhor, melhor_num, melhor_ativo = cells, numero, ativo

    _stream_rows(f"{BASE_URL}/redec_meteoro.php?action={action}", on_row)

    if melhor is None:
        return {}

    numero, data_criacao, _ativo, _validade, *valores_redec = melhor
    fonte = melhor[-1]
    criado_em = _parse_data_hora(data_criacao, "00:00:00")

    resultado = {}
    for redec, valor in zip(REDECS, valores_redec):
        risco = _normaliza_risco(valor)
        if risco is None:
            continue
        resultado[redec] = {
            "redec": redec,
            "risco": risco,
            "numero_externo": numero,
            "criado_em": criado_em,
            "fonte": fonte,
            "raw_payload": {"cells": melhor},
        }
    return resultado


def sync() -> AlertSyncResult:
    from core.models import RiskAlert

    result = AlertSyncResult()

    fetchers = [
        (RiskAlert.Tipo.HIDROLOGICO, lambda: _fetch_redec_log("hidrologico", f"{BASE_URL}/atualizacao_hidro.php")),
        (RiskAlert.Tipo.GEOLOGICO, lambda: _fetch_redec_log("geologico", f"{BASE_URL}/atualizacao_geo.php")),
        (RiskAlert.Tipo.METEOROLOGICO, lambda: _fetch_redec_bulletin(1)),
        (RiskAlert.Tipo.INCENDIO, lambda: _fetch_redec_bulletin(2)),
    ]

    for tipo, fetch in fetchers:
        try:
            por_redec = fetch()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao buscar alertas '%s'", tipo)
            result.errors.append(f"{tipo}: {exc}")
            continue
        for dados in por_redec.values():
            RiskAlert.objects.update_or_create(
                tipo=tipo, redec=dados["redec"], municipio="",
                defaults={k: v for k, v in dados.items() if k not in ("redec", "municipio")},
            )
            result.upserted += 1

    try:
        por_municipio_geo = _fetch_municipio(f"{BASE_URL}/atualizacao_municipio_geo.php")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao buscar alertas geológicos por município")
        result.errors.append(f"geologico_municipio: {exc}")
        por_municipio_geo = {}
    for dados in por_municipio_geo.values():
        RiskAlert.objects.update_or_create(
            tipo=RiskAlert.Tipo.GEOLOGICO, redec=dados["redec"], municipio=dados["municipio"],
            defaults={k: v for k, v in dados.items() if k not in ("redec", "municipio")},
        )
        result.upserted += 1

    # Hidrológico por município é diferente: a fonte só lista município a
    # partir do risco "ALTO" (confirmado pelo usuário) — ao contrário do
    # geológico, que sempre traz os 92. Isso significa que um município
    # pode SUMIR da resposta (quando o risco cai de volta pra moderado/
    # baixo), e se a gente só fizer upsert o registro antigo fica "preso"
    # em ALTO pra sempre. Por isso, apaga os que não vieram nesta rodada.
    try:
        por_municipio_hidro = _fetch_municipio(f"{BASE_URL}/atualizacao_municipio_hidro.php")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao buscar alertas hidrológicos por município")
        result.errors.append(f"hidrologico_municipio: {exc}")
        por_municipio_hidro = None

    if por_municipio_hidro is not None:
        RiskAlert.objects.filter(
            tipo=RiskAlert.Tipo.HIDROLOGICO
        ).exclude(municipio="").exclude(municipio__in=por_municipio_hidro.keys()).delete()
        for dados in por_municipio_hidro.values():
            RiskAlert.objects.update_or_create(
                tipo=RiskAlert.Tipo.HIDROLOGICO, redec=dados["redec"], municipio=dados["municipio"],
                defaults={k: v for k, v in dados.items() if k not in ("redec", "municipio")},
            )
            result.upserted += 1

    return result
