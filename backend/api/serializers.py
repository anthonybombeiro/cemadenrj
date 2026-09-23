from rest_framework import serializers

from core.models import AlertEvent, Reading, RiskAlert, Source, Station


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = ["id", "slug", "name", "website", "enabled", "last_ingested_at", "last_ingest_error"]


class LatestReadingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reading
        fields = ["reading_type", "value", "timestamp"]


class StationListSerializer(serializers.ModelSerializer):
    source = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    latest_readings = serializers.SerializerMethodField()

    class Meta:
        model = Station
        fields = [
            "id",
            "source",
            "external_id",
            "name",
            "municipality",
            "station_type",
            "status",
            "latitude",
            "longitude",
            "altitude_m",
            "latest_readings",
        ]

    def get_latest_readings(self, obj: Station):
        # IMPORTANTE: usar obj.readings.all() (não .order_by(...)) — chamar
        # .order_by() num related manager prefetched dispara uma query NOVA
        # pro banco, ignorando o cache do prefetch_related/Prefetch (N+1: uma
        # query por estação). Com 670 estações isso já chegou a estourar o
        # tempo do processo CGI em produção (HTTP 500 em /api/stations/).
        # A queryset do Prefetch (StationViewSet.get_queryset) já vem
        # filtrada por período recente e ordenada por (reading_type,
        # -timestamp), então aqui é só pegar a primeira ocorrência de cada
        # tipo, tudo em memória, sem tocar o banco de novo.
        latest_by_type = {}
        for reading in obj.readings.all():
            if reading.reading_type not in latest_by_type:
                latest_by_type[reading.reading_type] = reading
        return LatestReadingSerializer(latest_by_type.values(), many=True).data


class ReadingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reading
        fields = ["id", "reading_type", "value", "timestamp"]


class RiskAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskAlert
        fields = [
            "id",
            "tipo",
            "redec",
            "municipio",
            "risco",
            "numero_externo",
            "responsavel",
            "criado_em",
            "atualizado_em",
            "fonte",
        ]


class AlertEventSerializer(serializers.ModelSerializer):
    station_name = serializers.CharField(source="station.name", read_only=True)
    rule_name = serializers.CharField(source="rule.name", read_only=True)
    severity = serializers.CharField(source="rule.severity", read_only=True)

    class Meta:
        model = AlertEvent
        fields = ["id", "rule_name", "severity", "station", "station_name", "value", "triggered_at", "resolved_at"]
