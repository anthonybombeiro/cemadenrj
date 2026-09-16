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

ACOES_PERMITIDAS = {"migrate", "collectstatic", "ingest", "sync_risk_alerts"}


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
            elif action == "sync_risk_alerts":
                from ingestion.connectors import cemaden_rj_alertas

                resultado = cemaden_rj_alertas.sync()
                saida.write(resultado.summary())
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao executar ação administrativa %r", action)
            return Response({"detail": f"Erro: {exc}", "saida": saida.getvalue()}, status=500)

        return Response({"ok": True, "action": action, "saida": saida.getvalue()})
