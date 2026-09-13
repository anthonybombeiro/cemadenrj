from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.models import AlertEvent, Reading, Source, Station

from .serializers import (
    AlertEventSerializer,
    ReadingSerializer,
    SourceSerializer,
    StationListSerializer,
)


class SourceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Source.objects.all()
    serializer_class = SourceSerializer


class StationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StationListSerializer

    def get_queryset(self):
        qs = Station.objects.select_related("source").prefetch_related("readings")
        params = self.request.query_params
        if municipality := params.get("municipality"):
            qs = qs.filter(municipality__iexact=municipality)
        if station_type := params.get("station_type"):
            qs = qs.filter(station_type=station_type)
        if source := params.get("source"):
            qs = qs.filter(source__slug=source)
        return qs

    @action(detail=True, methods=["get"])
    def readings(self, request, pk=None):
        station = self.get_object()
        qs = station.readings.all()
        if reading_type := request.query_params.get("reading_type"):
            qs = qs.filter(reading_type=reading_type)
        limit = int(request.query_params.get("limit", 500))
        data = ReadingSerializer(qs[:limit], many=True).data
        return Response(data)


class AlertEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AlertEventSerializer

    def get_queryset(self):
        qs = AlertEvent.objects.select_related("rule", "station").order_by("-triggered_at")
        if self.request.query_params.get("active") == "true":
            qs = qs.filter(resolved_at__isnull=True)
        return qs
