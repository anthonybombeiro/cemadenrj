"""
Conector para as 225(+4) estações de sirene/alarme sonoro da CEMADEN-RJ,
via a API JSON AUTENTICADA do mesmo sistema do portal de sirenes
(sirene.cbmerj.rj.gov.br, hospedado no domínio do CBMERJ — operado pela
GridLab, confirmado pelo rodapé da tela de login: é a mesma empresa que
opera o painel comercial "oficial" da CEMADEN-RJ,
painelcemadenrj.defesacivil.rj.gov.br).

Diferente do `cemaden_rj_pluviometros.CemadenRJConnector` (página HTML
PÚBLICA, sem login, só com as ~85 leituras de chuva): esta API exige
login — um login de SERVIÇO criado especificamente pra essa automação
pelo diretor da CEMADEN-RJ em 2026-09-23 (`CEMADEN_RJ_SIRENES_USERNAME`/
`_PASSWORD` no `.env`, NUNCA a conta pessoal dele) — e devolve muito
mais:
  - coordenada EXATA de cada sirene (não o centroide do município, como
    o conector público);
  - status de acionamento em tempo real — se a sirene está TOCANDO agora.

Achado lendo o JS de `mapaFrame.jsp` (o iframe que desenha o mapa da área
autenticada). Fluxo de acesso:

  1. POST LoginControle?cmd=validandologin (usuario/senha/Login=Login,
     form-urlencoded) → 302 + cookie de sessão. Login simples via HTTP,
     sem JS/SPA — direto com `requests`, sem precisar de navegador.
  2. GET MapaControle?cmd=consultaEstacoesAtualiza (mesma sessão) → JSON
     com as 229 estações da rede GridLab/CEMADEN-RJ.

229 = 140 "Sirene" pura + 83 "Pluviômetro/Sirene" + 2
"Linímetro/Pluviômetro/Sirene" (225 = as sirenes de verdade, batendo
exatamente com o que o diretor descreveu) + 3 "Cancela" + 1 "Repetidora"
(não são sirenes — ignoradas). Das 225, 85 têm pluviômetro acoplado
(`pluviometro.idPluviometro != 0`) — "pra parametrizar os acionamentos
das 225" (palavras do diretor); essas 85 também viram Reading de chuva,
igual às outras fontes pluviométricas (bucket 15min, campo `tempo1`).

Status de acionamento (`logStatusEstacaoTemp`), lido da lógica de ícone
do próprio `mapaFrame.jsp` deles — NÃO confirmado operacionalmente linha
por linha pelo diretor (ele autorizou seguir com essa leitura em
2026-09-23, sem validação prática ainda; ver memória
`sirenes-225-estacoes-api`):
  - fk_idStatusEstacao: 1 = online, 2/3 = offline/manutenção.
  - fk_idStatusAcaoEstacao: 4 (ou 0) = normal/parada; qualquer outro
    valor = SIRENE TOCANDO (o ícone deles é literalmente "tocando.png"
    só nesse caso).

Cada acionamento vira um `AlertEvent` (mesmo modelo já usado pra alertas
de estação por limiar numérico) ligado a uma `AlertRule` "guarda-chuva"
única — criado quando a sirene começa a tocar, resolvido (`resolved_at`)
quando para, sem duplicar evento a cada sync enquanto continuar tocando.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import requests

from .cemaden_rj_pluviometros import _normaliza

logger = logging.getLogger("ingestion")

BASE_URL = "http://sirene.cbmerj.rj.gov.br:8080/sirenesestadorj"
LOGIN_URL = f"{BASE_URL}/LoginControle?cmd=validandologin"
ESTACOES_URL = f"{BASE_URL}/MapaControle?cmd=consultaEstacoesAtualiza"
TZ_RJ = ZoneInfo("America/Sao_Paulo")

SOURCE_SLUG = "cemaden_rj_sirenes"
SOURCE_NAME = "CEMADEN-RJ — Sirenes/Alarme (GridLab)"

# Valores de fk_idStatusAcaoEstacao que significam "sirene parada,
# normal" — qualquer outro valor é tratado como "tocando" (mesma lógica
# do ícone deles em mapaFrame.jsp: só usa "tocando.png" quando
# statusAcao != 4 e != 0).
STATUS_ACAO_NORMAL = {0, 4}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
}


def _login(usuario: str, senha: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    resp = session.post(
        LOGIN_URL,
        data={"usuario": usuario, "senha": senha, "Login": "Login"},
        timeout=30,
    )
    resp.raise_for_status()
    # Login errado não dá 401/403 nesse sistema — só re-renderiza a
    # própria tela de login. "IDENTIFIQUE-SE" é o texto fixo do <h3> dela.
    if "IDENTIFIQUE-SE" in resp.text:
        raise RuntimeError("Login recusado pelo portal de sirenes (usuário/senha incorretos?).")
    return session


def _parse_data_hora(valor: str) -> dt.datetime | None:
    valor = (valor or "").strip()
    try:
        naive = dt.datetime.strptime(valor, "%d/%m/%Y %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=TZ_RJ).astimezone(dt.timezone.utc)


def _to_float(valor) -> float | None:
    try:
        return float(str(valor).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


@dataclass
class SirenesSyncResult:
    stations_upserted: int = 0
    readings_created: int = 0
    sirenes_tocando: int = 0
    eventos_criados: int = 0
    eventos_resolvidos: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"estações: {self.stations_upserted} | leituras: +{self.readings_created} | "
            f"sirenes tocando agora: {self.sirenes_tocando} "
            f"(novos eventos: {self.eventos_criados}, resolvidos: {self.eventos_resolvidos}) | "
            f"erros: {len(self.errors)}"
        )


def _regra_sirene():
    from core.models import AlertRule, Reading

    regra, _ = AlertRule.objects.get_or_create(
        name="Sirene de alarme tocando",
        defaults={
            # reading_type/comparison/threshold_value são exigidos pelo
            # modelo mas não usados de verdade aqui — quem decide se a
            # sirene está tocando é o status que a própria GridLab manda
            # (fk_idStatusAcaoEstacao), não uma leitura numérica nossa.
            "reading_type": Reading.ReadingType.CHUVA_MM,
            "comparison": AlertRule.Comparison.GTE,
            "threshold_value": 0,
            "severity": AlertRule.Severity.ALERTA_MAXIMO,
            "active": True,
        },
    )
    return regra


def sync() -> SirenesSyncResult:
    from django.conf import settings
    from django.utils import timezone

    from core.models import AlertEvent, Reading, Source, Station

    result = SirenesSyncResult()
    usuario = getattr(settings, "CEMADEN_RJ_SIRENES_USERNAME", "")
    senha = getattr(settings, "CEMADEN_RJ_SIRENES_PASSWORD", "")
    if not usuario or not senha:
        result.errors.append("CEMADEN_RJ_SIRENES_USERNAME/PASSWORD não configurados no .env.")
        return result

    try:
        session = _login(usuario, senha)
        resp = session.get(ESTACOES_URL, timeout=30)
        resp.raise_for_status()
        registros = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao buscar estações de sirene do CEMADEN-RJ")
        result.errors.append(str(exc))
        return result

    source, _ = Source.objects.get_or_create(
        slug=SOURCE_SLUG,
        defaults={
            "name": SOURCE_NAME,
            "website": BASE_URL,
            "description": (
                "Rede de sirenes de alerta/alarme da CEMADEN-RJ (via portal autenticado, operado pela GridLab)."
            ),
        },
    )
    regra = _regra_sirene()
    now = timezone.now()

    for registro in registros:
        tipo_equip = (registro.get("equipamento") or {}).get("tipoEquipamento", "")
        if "Sirene" not in tipo_equip and "Linímetro" not in tipo_equip:
            continue  # Cancela/Repetidora — não são sirenes, fora do escopo aqui

        lat = _to_float(registro.get("latitude"))
        lon = _to_float(registro.get("longitude"))
        if lat is None or lon is None:
            logger.warning("Sirene id %s sem lat/lon válida, ignorada.", registro.get("idEstacao"))
            continue

        # `idEstacao` NÃO é único globalmente (testado: só 36 valores
        # distintos nas 225 sirenes) — é escopado por grupo/cidade na
        # base deles (a mesma "Estação 2" existe em Angra, Areal, Barra
        # Mansa, ...). `idGrupo` também não resolve (26 grupos abrangem
        # mais de uma cidade). O que É único nas 225: cidade+nome da
        # estação (conferido) — mesma estratégia de chave sintética já
        # usada em `cemaden_rj_pluviometros.py` pra fonte pública.
        external_id = f"{_normaliza(registro.get('cidade', ''))}|{_normaliza(registro.get('nomeEstacao', ''))}"
        status_log = registro.get("logStatusEstacaoTemp") or {}
        status_estacao = status_log.get("fk_idStatusEstacao")
        status_acao = status_log.get("fk_idStatusAcaoEstacao")

        station, _ = Station.objects.update_or_create(
            source=source,
            external_id=external_id,
            defaults={
                "name": registro.get("nomeEstacao") or f"Sirene {external_id}",
                "municipality": registro.get("cidade", ""),
                "station_type": Station.StationType.SIRENE,
                "status": Station.Status.ATIVA if status_estacao == 1 else Station.Status.INATIVA,
                "latitude": lat,
                "longitude": lon,
                "altitude_m": None,
                "raw_metadata": {
                    "id_estacao_origem": registro.get("idEstacao"),  # NÃO único, só referência
                    "id_grupo_origem": (registro.get("grupo") or {}).get("idGrupo"),
                    "descricao": registro.get("descricaoEstacao"),
                    "rua": registro.get("rua"),
                    "numero": registro.get("numero"),
                    "bairro": registro.get("bairro"),
                    "redec": registro.get("nomeRedec"),
                    "grupo": (registro.get("grupo") or {}).get("nomeGrupo"),
                    "tipo_equipamento": tipo_equip,
                    "tem_pluviometro": (registro.get("pluviometro") or {}).get("idPluviometro", 0) != 0,
                },
            },
        )
        result.stations_upserted += 1

        pluv = registro.get("pluviometro") or {}
        if pluv.get("idPluviometro", 0) != 0:
            valor = _to_float(pluv.get("tempo1"))
            timestamp = _parse_data_hora(pluv.get("DataHora", ""))
            if valor is not None and timestamp is not None:
                _, criado = Reading.objects.get_or_create(
                    station=station,
                    reading_type=Reading.ReadingType.CHUVA_MM,
                    timestamp=timestamp,
                    defaults={"value": valor, "raw_payload": pluv},
                )
                if criado:
                    result.readings_created += 1

        tocando = status_acao is not None and status_acao not in STATUS_ACAO_NORMAL
        evento_ativo = AlertEvent.objects.filter(rule=regra, station=station, resolved_at__isnull=True).first()
        if tocando:
            result.sirenes_tocando += 1
            if evento_ativo is None:
                AlertEvent.objects.create(rule=regra, station=station, value=float(status_acao))
                result.eventos_criados += 1
        elif evento_ativo is not None:
            evento_ativo.resolved_at = now
            evento_ativo.save(update_fields=["resolved_at"])
            result.eventos_resolvidos += 1

    return result
