"""
Endpoint de ingestão remota: recebe leituras já normalizadas de um worker
externo (o scraper do INMET rodando no GitHub Actions, que tem um Chrome de
verdade disponível de graça — o HostGator compartilhado não tem).

Protegido por um segredo compartilhado (header `X-Ingest-Secret`), não por
autenticação de usuário — é uma máquina conversando com outra, não uma
sessão de operador. Ver docs/fontes-de-dados.md e
.github/workflows/scrape-inmet.yml.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Reading, Source, Station

logger = logging.getLogger("ingestion")


class RemoteReadingsIngestView(APIView):
    """POST /api/ingest/readings/

    Body esperado:
        {
          "source_slug": "inmet",
          "readings": [
            {"external_id": "A652", "reading_type": "temperatura_c",
             "value": 19.9, "timestamp": "2026-09-13T06:00:00Z",
             "raw_payload": {...}},
            ...
          ]
        }

    A estação (`Station`) precisa já existir (criada por
    `python manage.py ingest inmet`, que popula a lista de estações via API
    JSON pública — isso roda sem problema no HostGator). Este endpoint só
    grava leituras em estações já conhecidas; nunca cria estação nova.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    def post(self, request):
        secret_esperado = getattr(settings, "INGEST_SHARED_SECRET", "")
        secret_recebido = request.headers.get("X-Ingest-Secret", "")
        if not secret_esperado or secret_recebido != secret_esperado:
            logger.warning("Tentativa de ingestão remota com segredo inválido/ausente.")
            return Response({"detail": "Não autorizado."}, status=401)

        payload = request.data
        source_slug = payload.get("source_slug")
        readings_in = payload.get("readings", [])
        if not source_slug or not isinstance(readings_in, list):
            return Response({"detail": "Payload inválido: esperado 'source_slug' e 'readings' (lista)."}, status=400)

        try:
            source = Source.objects.get(slug=source_slug)
        except Source.DoesNotExist:
            return Response(
                {"detail": f"Fonte '{source_slug}' não encontrada. Rode 'python manage.py ingest {source_slug}' "
                           "no servidor ao menos uma vez para criar a fonte e as estações."},
                status=404,
            )

        criadas = 0
        duplicadas = 0
        estacoes_nao_encontradas = set()
        tipos_invalidos = set()

        valid_types = {c for c, _ in Reading.ReadingType.choices}

        for item in readings_in:
            try:
                external_id = item["external_id"]
                reading_type = item["reading_type"]
                value = float(item["value"])
                ts = item["timestamp"]
            except (KeyError, TypeError, ValueError):
                continue

            if reading_type not in valid_types:
                tipos_invalidos.add(reading_type)
                continue

            try:
                station = Station.objects.get(source=source, external_id=external_id)
            except Station.DoesNotExist:
                estacoes_nao_encontradas.add(external_id)
                continue

            _, created = Reading.objects.get_or_create(
                station=station,
                reading_type=reading_type,
                timestamp=ts,
                defaults={"value": value, "raw_payload": item.get("raw_payload", {})},
            )
            if created:
                criadas += 1
            else:
                duplicadas += 1

        source.last_ingested_at = timezone.now()
        source.save(update_fields=["last_ingested_at"])

        return Response(
            {
                "leituras_criadas": criadas,
                "leituras_duplicadas": duplicadas,
                "estacoes_nao_encontradas": sorted(estacoes_nao_encontradas),
                "tipos_invalidos": sorted(tipos_invalidos),
            }
        )
