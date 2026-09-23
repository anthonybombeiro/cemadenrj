import datetime
from collections import defaultdict

from django.db.models import Max, Prefetch, Sum
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
#   - "running_daily": o valor é um total corrido desde a meia-noite local.
#     Somar leituras dobraria a contagem — o valor mais recente já É o
#     acumulado do dia. Nenhuma fonte ativa usa mais essa categoria desde
#     2026-09-23: Wunderground/Plugfield relatam total corrido na origem
#     (precipTotal/rainDay), mas os conectores já convertem pra "balde" na
#     ingestão (ver bucket_from_running_daily em
#     ingestion/connectors/base.py — pedido do usuário, precisava do dado
#     "escalonado igual às demais" pra consulta futura direto no banco).
#     Mantido aqui só como categoria disponível, caso uma fonte nova
#     apareça sem essa conversão.
PRECIPITACAO_BUCKET_SOURCES = {
    "alerta_rio",
    "cemaden_nacional",
    "inmet",
    "rio_chuva_bairro",
    "cemaden_mctic",
    "niteroi",
    "cemaden_rj_sirenes",
    "inea",
    "wunderground",
    "plugfield",
}
PRECIPITACAO_RUNNING_DAILY_SOURCES: set[str] = set()


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
        # Prefetch com queryset PRÓPRIO (filtrado + ordenado) em vez de
        # `.prefetch_related("readings")` cru — dois motivos:
        #   1. Sem isso, 670+ estações cada uma acumulando semanas de
        #      leitura a cada ~15min vira um prefetch gigante (todo o
        #      histórico de todas as estações numa passada só) — já bateu
        #      timeout/erro 500 em produção (processo CGI do HostGator,
        #      sem os recursos de um servidor dedicado). Cortar pras
        #      leituras dos últimos 7 dias é mais que suficiente pra achar
        #      a "última leitura de cada tipo" de qualquer estação viva.
        #   2. Já vem ordenado por (reading_type, -timestamp) — o
        #      serializer só precisa pegar a primeira ocorrência de cada
        #      tipo, sem precisar ordenar de novo em Python nem (pior)
        #      chamar `.order_by()` no related manager, que dispararia uma
        #      query nova POR ESTAÇÃO (N+1) — ver StationListSerializer.
        cutoff = timezone.now() - datetime.timedelta(days=7)
        leituras_recentes = Reading.objects.filter(timestamp__gte=cutoff).order_by("reading_type", "-timestamp")
        return self._filtered_stations().prefetch_related(Prefetch("readings", queryset=leituras_recentes))

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
        """Estações pluviométricas com chuva acumulada em várias janelas —
        inspirado no formato do Alerta Rio (websempre.rio.rj.gov.br/estacoes/)
        e do portal de sirenes do CEMADEN-RJ, pedido pelo usuário pra ter
        o mesmo leque de janelas que essas referências.

        Endpoint dedicado (em vez de calcular isso no serializer padrão)
        porque exige somar leituras de "chuva_mm" — caro demais pra rodar
        em toda chamada de /api/stations/, que é usada pelo mapa e pela
        tabela meteorológica onde isso não é necessário.

        5min/10min/15min/30min/1h/2h/3h/4h/6h/12h/24h/36h/48h/72h/96h são
        todos derivados das MESMAS leituras já buscadas (até 96h atrás) —
        filtrar em Python por cutoff é essencialmente grátis uma vez que
        as linhas já estão em memória, sem custo de query adicional. Pra
        fontes de cadência mais lenta que a janela (ex: INMET de 1h só
        atualiza de hora em hora), 5min/10min/15min naturalmente saem
        iguais a "Agora" — não é bug, é a granularidade real da fonte.

        168h (7 dias), "1 mês" (janela corrida de 30 dias, não confundir
        com "no mês" abaixo) e "pico" (maior leitura individual nas
        últimas 24h — nosso equivalente ao "TX-15" do Alerta Rio, sem
        assumir literalmente 15min já que a cadência varia por fonte) SÃO
        agregados NO BANCO (Sum/Max agrupados por estação, uma linha por
        estação na resposta) — não traz o histórico bruto de até 30 dias
        pra memória do processo, o que já se mostrou arriscado no
        HostGator (ver o incidente de N+1/payload gigante corrigido antes
        em StationListSerializer). "no mês" (desde o dia 1 do mês
        corrente, hora local — calendário, não janela corrida) também.
        """
        stations = list(
            self._filtered_stations()
            .filter(readings__reading_type=Reading.ReadingType.CHUVA_MM)
            .distinct()
        )
        station_ids = [s.id for s in stations]

        now = timezone.now()
        # Campos calculados em Python a partir das leituras já buscadas
        # (até 96h atrás, ver JANELA_MAX_PYTHON abaixo).
        cutoffs = {
            "acumulado_5min_mm": now - datetime.timedelta(minutes=5),
            "acumulado_10min_mm": now - datetime.timedelta(minutes=10),
            "acumulado_15min_mm": now - datetime.timedelta(minutes=15),
            "acumulado_30min_mm": now - datetime.timedelta(minutes=30),
            "acumulado_1h_mm": now - datetime.timedelta(hours=1),
            "acumulado_2h_mm": now - datetime.timedelta(hours=2),
            "acumulado_3h_mm": now - datetime.timedelta(hours=3),
            "acumulado_4h_mm": now - datetime.timedelta(hours=4),
            "acumulado_6h_mm": now - datetime.timedelta(hours=6),
            "acumulado_12h_mm": now - datetime.timedelta(hours=12),
            "acumulado_24h_mm": now - datetime.timedelta(hours=24),
            "acumulado_36h_mm": now - datetime.timedelta(hours=36),
            "acumulado_48h_mm": now - datetime.timedelta(hours=48),
            "acumulado_72h_mm": now - datetime.timedelta(hours=72),
            "acumulado_96h_mm": now - datetime.timedelta(hours=96),
        }
        JANELA_MAX_PYTHON = cutoffs["acumulado_96h_mm"]

        # Campos agregados NO BANCO (janela maior que 96h, ou calendário).
        cutoff_168h = now - datetime.timedelta(hours=168)
        cutoff_1mes_corrido = now - datetime.timedelta(days=30)
        inicio_hoje_local = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        inicio_mes_calendario = inicio_hoje_local.replace(day=1)

        readings = Reading.objects.filter(
            station_id__in=station_ids,
            reading_type=Reading.ReadingType.CHUVA_MM,
            timestamp__gte=JANELA_MAX_PYTHON,
        ).values("station_id", "value", "timestamp")

        by_station = defaultdict(list)
        for r in readings:
            by_station[r["station_id"]].append(r)

        def _soma_agregada_por_estacao(cutoff):
            return {
                row["station_id"]: row["total"]
                for row in Reading.objects.filter(
                    station_id__in=station_ids, reading_type=Reading.ReadingType.CHUVA_MM, timestamp__gte=cutoff
                )
                .values("station_id")
                .annotate(total=Sum("value"))
            }

        soma_168h_por_estacao = _soma_agregada_por_estacao(cutoff_168h)
        soma_1mes_corrido_por_estacao = _soma_agregada_por_estacao(cutoff_1mes_corrido)
        soma_mes_calendario_por_estacao = _soma_agregada_por_estacao(inicio_mes_calendario)
        pico_24h_por_estacao = {
            row["station_id"]: row["maior"]
            for row in Reading.objects.filter(
                station_id__in=station_ids,
                reading_type=Reading.ReadingType.CHUVA_MM,
                timestamp__gte=cutoffs["acumulado_24h_mm"],
            )
            .values("station_id")
            .annotate(maior=Max("value"))
        }

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
                "acumulado_168h_mm": None,
                "acumulado_1mes_mm": None,
                "acumulado_mes_mm": None,
                "pico_mm": None,
                **{campo: None for campo in cutoffs},
            }
            if kind == "bucket":
                entry["chuva_agora_mm"] = latest["value"] if latest else None
                for campo, cutoff in cutoffs.items():
                    entry[campo] = sum(r["value"] for r in rows if r["timestamp"] >= cutoff)
                entry["acumulado_hoje_mm"] = sum(
                    r["value"] for r in rows if r["timestamp"] >= inicio_hoje_local
                )
                entry["acumulado_168h_mm"] = soma_168h_por_estacao.get(station.id)
                entry["acumulado_1mes_mm"] = soma_1mes_corrido_por_estacao.get(station.id)
                entry["acumulado_mes_mm"] = soma_mes_calendario_por_estacao.get(station.id)
                entry["pico_mm"] = pico_24h_por_estacao.get(station.id)
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
