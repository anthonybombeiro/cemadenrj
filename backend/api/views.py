import datetime
from collections import defaultdict

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.models import AlertEvent, Reading, RiskAlert, Source, Station

from .serializers import (
    AlertEventSerializer,
    ReadingSerializer,
    RiskAlertSerializer,
    SourceSerializer,
    StationListSerializer,
)

# Cada fonte relata "chuva_mm" com semântica diferente — misturar as duas sem
# distinguir dá número errado (dobra ou infla contagem):
#   - "bucket": o valor é a chuva NA JANELA daquela leitura (ex: Alerta Rio
#     m15 = chuva nos últimos 15min, INMET CHUVA = chuva na última hora).
#     Somar leituras no período é válido.
#   - "running_daily": o valor é um total corrido desde a meia-noite local
#     (ex: Wunderground precipTotal, Plugfield rainDay). Somar leituras
#     dobraria a contagem — o valor mais recente já É o acumulado do dia.
PRECIPITACAO_BUCKET_SOURCES = {
    "alerta_rio",
    "cemaden_nacional",
    "inmet",
    "rio_chuva_bairro",
    "cemaden_rj",
    "cemaden_mctic",
    "niteroi",
}
PRECIPITACAO_RUNNING_DAILY_SOURCES = {"wunderground", "plugfield"}


class SourceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Source.objects.all()
    serializer_class = SourceSerializer


class StationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StationListSerializer

    def _filtered_stations(self):
        qs = Station.objects.select_related("source")
        params = self.request.query_params
        if municipality := params.get("municipality"):
            qs = qs.filter(municipality__iexact=municipality)
        if station_type := params.get("station_type"):
            qs = qs.filter(station_type=station_type)
        if source := params.get("source"):
            qs = qs.filter(source__slug=source)
        return qs

    def get_queryset(self):
        return self._filtered_stations().prefetch_related("readings")

    @action(detail=True, methods=["get"])
    def readings(self, request, pk=None):
        station = self.get_object()
        qs = station.readings.all()
        if reading_type := request.query_params.get("reading_type"):
            qs = qs.filter(reading_type=reading_type)
        limit = int(request.query_params.get("limit", 500))
        data = ReadingSerializer(qs[:limit], many=True).data
        return Response(data)

    @action(detail=False, methods=["get"])
    def precipitacao(self, request):
        """Estações pluviométricas com chuva acumulada em janelas padrão.

        Endpoint dedicado (em vez de calcular isso no serializer padrão)
        porque exige somar leituras de "chuva_mm" das últimas 96h — caro
        demais pra rodar em toda chamada de /api/stations/, que é usada
        pelo mapa e pela tabela meteorológica onde isso não é necessário.
        """
        stations = list(
            self._filtered_stations()
            .filter(readings__reading_type=Reading.ReadingType.CHUVA_MM)
            .distinct()
        )

        now = timezone.now()
        cutoff_96h = now - datetime.timedelta(hours=96)
        cutoff_24h = now - datetime.timedelta(hours=24)
        cutoff_1h = now - datetime.timedelta(hours=1)
        inicio_hoje_local = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)

        readings = Reading.objects.filter(
            station_id__in=[s.id for s in stations],
            reading_type=Reading.ReadingType.CHUVA_MM,
            timestamp__gte=cutoff_96h,
        ).values("station_id", "value", "timestamp")

        by_station = defaultdict(list)
        for r in readings:
            by_station[r["station_id"]].append(r)

        data = []
        for station in stations:
            slug = station.source.slug
            kind = (
                "bucket"
                if slug in PRECIPITACAO_BUCKET_SOURCES
                else "running_daily" if slug in PRECIPITACAO_RUNNING_DAILY_SOURCES else None
            )
            rows = sorted(by_station.get(station.id, []), key=lambda r: r["timestamp"])
            latest = rows[-1] if rows else None

            entry = {
                "id": station.id,
                "source": slug,
                "station_type": station.station_type,
                "external_id": station.external_id,
                "name": station.name,
                "municipality": station.municipality,
                "latitude": station.latitude,
                "longitude": station.longitude,
                "updated_at": latest["timestamp"] if latest else None,
                "chuva_agora_mm": None,
                "acumulado_hoje_mm": None,
                "acumulado_1h_mm": None,
                "acumulado_24h_mm": None,
                "acumulado_96h_mm": None,
            }
            if kind == "bucket":
                entry["chuva_agora_mm"] = latest["value"] if latest else None
                entry["acumulado_1h_mm"] = sum(r["value"] for r in rows if r["timestamp"] >= cutoff_1h)
                entry["acumulado_24h_mm"] = sum(r["value"] for r in rows if r["timestamp"] >= cutoff_24h)
                entry["acumulado_96h_mm"] = sum(r["value"] for r in rows)
                entry["acumulado_hoje_mm"] = sum(
                    r["value"] for r in rows if r["timestamp"] >= inicio_hoje_local
                )
            elif kind == "running_daily":
                entry["acumulado_hoje_mm"] = latest["value"] if latest else None
            data.append(entry)

        return Response(data)


class AlertEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AlertEventSerializer

    def get_queryset(self):
        qs = AlertEvent.objects.select_related("rule", "station").order_by("-triggered_at")
        if self.request.query_params.get("active") == "true":
            qs = qs.filter(resolved_at__isnull=True)
        return qs


class RiskAlertViewSet(viewsets.ReadOnlyModelViewSet):
    """Classificações de risco oficiais da Defesa Civil-RJ (hidrológico,
    geológico, severidade meteorológica, incêndio florestal) — ver
    ingestion/connectors/cemaden_rj_alertas.py."""

    serializer_class = RiskAlertSerializer

    def get_queryset(self):
        qs = RiskAlert.objects.all()
        params = self.request.query_params
        if tipo := params.get("tipo"):
            qs = qs.filter(tipo=tipo)
        if params.get("escopo") == "redec":
            qs = qs.filter(municipio="")
        elif params.get("escopo") == "municipio":
            qs = qs.exclude(municipio="")
        return qs
