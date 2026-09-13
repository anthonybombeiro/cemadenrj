"""
Interface comum para conectores de fontes externas de dados meteo/hidrológicos.

Cada conector implementa `fetch_stations()` e `fetch_readings(stations)`,
retornando dicionários já normalizados (ver formatos abaixo). O método
`run()` cuida do upsert no banco — os conectores não tocam o Django ORM
diretamente, o que mantém a parte de "falar com a API externa" isolada e
fácil de testar/trocar (é aqui que entra, por exemplo, um futuro conector
para o painel GridLab da CEMADEN-RJ assim que o acesso institucional for
concedido).

Formato de estação normalizada (dict):
    {
        "external_id": str,
        "name": str,
        "municipality": str,          # pode ser "" se desconhecido
        "station_type": Station.StationType,
        "status": Station.Status,
        "latitude": float,
        "longitude": float,
        "altitude_m": float | None,
        "raw_metadata": dict,
    }

Formato de leitura normalizada (dict):
    {
        "external_id": str,           # código da estação a que pertence
        "reading_type": Reading.ReadingType,
        "value": float,
        "timestamp": datetime (aware, UTC),
        "raw_payload": dict,
    }
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("ingestion")


@dataclass
class IngestResult:
    stations_created: int = 0
    stations_updated: int = 0
    readings_created: int = 0
    readings_skipped_duplicate: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"estações: +{self.stations_created} / atualizadas {self.stations_updated} | "
            f"leituras: +{self.readings_created} (dup. ignoradas: {self.readings_skipped_duplicate}) | "
            f"erros: {len(self.errors)}"
        )


class BaseConnector:
    slug: str = ""
    name: str = ""
    website: str = ""
    description: str = ""

    def fetch_stations(self) -> list[dict]:
        raise NotImplementedError

    def fetch_readings(self, stations: list[dict]) -> list[dict]:
        raise NotImplementedError

    def run(self) -> IngestResult:
        # Import tardio para não acoplar o módulo de conectores ao Django
        # no momento da importação (facilita testar conectores isolados).
        from django.utils import timezone

        from core.models import Reading, Source, Station

        result = IngestResult()
        source, _ = Source.objects.get_or_create(
            slug=self.slug,
            defaults={"name": self.name, "website": self.website, "description": self.description},
        )

        try:
            station_dicts = self.fetch_stations()
        except Exception as exc:  # noqa: BLE001 - queremos capturar e registrar qualquer falha de rede/parsing
            logger.exception("Falha ao buscar estações de %s", self.slug)
            result.errors.append(f"fetch_stations: {exc}")
            source.last_ingest_error = str(exc)
            source.save(update_fields=["last_ingest_error"])
            return result

        station_objs_by_external_id: dict[str, Station] = {}
        for sd in station_dicts:
            obj, created = Station.objects.update_or_create(
                source=source,
                external_id=sd["external_id"],
                defaults={
                    "name": sd["name"],
                    "municipality": sd.get("municipality", ""),
                    "station_type": sd.get("station_type", Station.StationType.OUTRO),
                    "status": sd.get("status", Station.Status.DESCONHECIDO),
                    "latitude": sd["latitude"],
                    "longitude": sd["longitude"],
                    "altitude_m": sd.get("altitude_m"),
                    "raw_metadata": sd.get("raw_metadata", {}),
                },
            )
            station_objs_by_external_id[sd["external_id"]] = obj
            if created:
                result.stations_created += 1
            else:
                result.stations_updated += 1

        try:
            reading_dicts = self.fetch_readings(station_dicts)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao buscar leituras de %s", self.slug)
            result.errors.append(f"fetch_readings: {exc}")
            reading_dicts = []

        for rd in reading_dicts:
            station = station_objs_by_external_id.get(rd["external_id"])
            if station is None:
                continue
            _, created = Reading.objects.get_or_create(
                station=station,
                reading_type=rd["reading_type"],
                timestamp=rd["timestamp"],
                defaults={"value": rd["value"], "raw_payload": rd.get("raw_payload", {})},
            )
            if created:
                result.readings_created += 1
            else:
                result.readings_skipped_duplicate += 1

        source.last_ingested_at = timezone.now()
        source.last_ingest_error = "; ".join(result.errors)
        source.save(update_fields=["last_ingested_at", "last_ingest_error"])
        return result
