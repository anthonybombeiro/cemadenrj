"""
Endpoint de operações administrativas via HTTP — existe só porque o plano
compartilhado do HostGator não dá acesso a shell (confirmado: "Shell
access is not enabled on your account"), então não há como rodar
`python manage.py migrate`/`ingest` por SSH. Isso permite disparar essas
mesmas ações via um POST autenticado por segredo — chamado manualmente
uma vez para o setup inicial (migrate) e depois pelos Cron Jobs do cPanel
(curl) para a ingestão periódica.

Deliberadamente uma lista BRANCA fixa de ações (nunca comando arbitrário):
  - "migrate": roda as migrations do Django
  - "collectstatic": coleta arquivos estáticos (admin do Django)
  - "ingest": roda um conector específico (source obrigatório, tem que
    estar no REGISTRY de ingestion/connectors)
  - "sync_risk_alerts": roda ingestion/connectors/cemaden_rj_alertas.py
    (alertas oficiais de risco da Defesa Civil-RJ — não é um conector
    Station/Reading, por isso não está no REGISTRY normal)
  - "sync_sirenes": roda ingestion/connectors/cemaden_rj_sirenes.py (as
    225 sirenes de alerta/alarme da CEMADEN-RJ, via API autenticada —
    também fora do REGISTRY normal, porque além de Station/Reading isso
    também cria/resolve AlertEvent de acionamento)
  - "delete_stations": apaga estações de UMA fonte cujo external_id
    bate com um filtro — usado pra limpar registros órfãos quando um
    conector muda o jeito de calcular o external_id (ex: cemaden_mctic já
    trocou duas vezes: chave sintética "cidade|nome" → código oficial
    tipo "330580216A" → id numérico do CEMADEN nacional; a cada troca as
    antigas ficam órfãs, nunca mais recebem leitura). Exige source +
    (external_id_contains e/ou external_id_regex) — nunca apaga a fonte
    inteira sem pelo menos um desses dois filtros.
  - "purge_readings": apaga leituras de UM tipo de UMA fonte a partir de
    um timestamp (ISO) — usado pra migração quando o SIGNIFICADO de um
    valor já armazenado muda (ex: 2026-09-23, Wunderground/Plugfield
    passaram de "total corrido do dia" pra "balde por intervalo" — as
    leituras de HOJE gravadas antes da mudança ficam contaminando a soma
    como se fossem baldes, gerando acumulado absurdo). Exige source +
    reading_type + since (formato "YYYY-MM-DDTHH:MM:SS", sempre UTC).
"""

from __future__ import annotations

import io
import logging

from django.conf import settings
from django.core.management import call_command
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger("ingestion")

ACOES_PERMITIDAS = {
    "migrate",
    "collectstatic",
    "ingest",
    "sync_risk_alerts",
    "sync_sirenes",
    "delete_stations",
    "purge_readings",
}


class AdminOpsView(APIView):
    """POST /api/admin/run/
    Headers: X-Admin-Secret: <ADMIN_TRIGGER_SECRET>
    Body: {"action": "migrate"} | {"action": "collectstatic"} |
          {"action": "ingest", "source": "inmet"}
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    def post(self, request):
        secret_esperado = getattr(settings, "ADMIN_TRIGGER_SECRET", "")
        secret_recebido = request.headers.get("X-Admin-Secret", "")
        if not secret_esperado or secret_recebido != secret_esperado:
            logger.warning("Tentativa de acionar /api/admin/run/ com segredo inválido/ausente.")
            return Response({"detail": "Não autorizado."}, status=401)

        action = (request.data or {}).get("action")
        if action not in ACOES_PERMITIDAS:
            return Response(
                {"detail": f"Ação inválida. Permitidas: {sorted(ACOES_PERMITIDAS)}"}, status=400
            )

        saida = io.StringIO()
        try:
            if action == "migrate":
                call_command("migrate", interactive=False, stdout=saida, stderr=saida)
            elif action == "collectstatic":
                call_command("collectstatic", interactive=False, verbosity=1, stdout=saida, stderr=saida)
            elif action == "ingest":
                from ingestion.connectors import REGISTRY, get_connector

                source = (request.data or {}).get("source")
                if source not in REGISTRY:
                    return Response(
                        {"detail": f"source inválido. Disponíveis: {sorted(REGISTRY)}"}, status=400
                    )
                resultado = get_connector(source).run()
                saida.write(resultado.summary())
                for erro in resultado.errors:
                    saida.write(f"\n  - {erro}")
            elif action == "sync_risk_alerts":
                from ingestion.connectors import cemaden_rj_alertas

                resultado = cemaden_rj_alertas.sync()
                saida.write(resultado.summary())
            elif action == "sync_sirenes":
                from ingestion.connectors import cemaden_rj_sirenes

                resultado = cemaden_rj_sirenes.sync()
                saida.write(resultado.summary())
            elif action == "delete_stations":
                import re as re_module

                from core.models import Station

                source = (request.data or {}).get("source")
                contains = (request.data or {}).get("external_id_contains")
                regex = (request.data or {}).get("external_id_regex")
                if not source or not (contains or regex):
                    return Response(
                        {
                            "detail": (
                                "delete_stations exige 'source' e pelo menos um de "
                                "'external_id_contains' / 'external_id_regex'."
                            )
                        },
                        status=400,
                    )
                # Filtra em Python, não em SQL: o MySQL 5.7 de produção não
                # tem REGEXP_LIKE (só chegou no 8.0.4+), que é o que o
                # Django gera por baixo de __regex/__iregex nesse servidor
                # — dá erro "(1305, 'FUNCTION ...REGEXP_LIKE does not
                # exist')" mesmo pedindo a variante case-sensitive. Buscar
                # os pares (id, external_id) e filtrar aqui evita depender
                # de qual dialeto de regex o banco tem disponível.
                candidatos = Station.objects.filter(source__slug=source).values_list("id", "external_id")
                padrao = re_module.compile(regex) if regex else None

                def _bate(external_id: str) -> bool:
                    # AND entre os filtros informados — igual ao .filter()
                    # encadeado que isso substitui: se os dois vierem, os
                    # dois precisam bater, não é OU.
                    if contains and contains not in external_id:
                        return False
                    if padrao and not padrao.search(external_id):
                        return False
                    return True

                ids_para_apagar = [pk for pk, external_id in candidatos if _bate(external_id)]
                apagadas, _ = Station.objects.filter(pk__in=ids_para_apagar).delete()
                saida.write(f"objetos apagados (estação + leituras em cascata): {apagadas}")
            elif action == "purge_readings":
                import datetime as dt_module

                from core.models import Reading

                source = (request.data or {}).get("source")
                reading_type = (request.data or {}).get("reading_type")
                since_str = (request.data or {}).get("since")
                if not source or not reading_type or not since_str:
                    return Response(
                        {"detail": "purge_readings exige 'source', 'reading_type' e 'since' (ISO, UTC)."},
                        status=400,
                    )
                try:
                    since = dt_module.datetime.fromisoformat(since_str).replace(tzinfo=dt_module.timezone.utc)
                except ValueError:
                    return Response({"detail": f"'since' inválido: {since_str!r}"}, status=400)
                apagadas, _ = Reading.objects.filter(
                    station__source__slug=source, reading_type=reading_type, timestamp__gte=since
                ).delete()
                saida.write(f"leituras apagadas: {apagadas}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao executar ação administrativa %r", action)
            return Response({"detail": f"Erro: {exc}", "saida": saida.getvalue()}, status=500)

        return Response({"ok": True, "action": action, "saida": saida.getvalue()})
