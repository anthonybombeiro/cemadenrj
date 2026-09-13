from django.db import models


class Source(models.Model):
    """Uma fonte externa de dados (INMET, CEMADEN nacional, Alerta Rio, ...)."""

    slug = models.SlugField(unique=True, help_text="Identificador usado pelo conector (ex: 'inmet').")
    name = models.CharField(max_length=120)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    last_ingested_at = models.DateTimeField(null=True, blank=True)
    last_ingest_error = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Station(models.Model):
    class StationType(models.TextChoices):
        PLUVIOMETRICA = "pluviometrica", "Pluviométrica (chuva)"
        HIDROLOGICA = "hidrologica", "Hidrológica (nível de rio)"
        METEOROLOGICA = "meteorologica", "Meteorológica (completa)"
        MARE = "mare", "Maré/Oceanográfica"
        OUTRO = "outro", "Outro"

    class Status(models.TextChoices):
        ATIVA = "ativa", "Ativa"
        INATIVA = "inativa", "Inativa"
        DESCONHECIDO = "desconhecido", "Desconhecido"

    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="stations")
    external_id = models.CharField(
        max_length=64, help_text="Código da estação na fonte original (ex: código INMET 'A652')."
    )
    name = models.CharField(max_length=200)
    municipality = models.CharField(max_length=120, blank=True)
    station_type = models.CharField(max_length=20, choices=StationType.choices, default=StationType.OUTRO)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DESCONHECIDO)
    latitude = models.FloatField()
    longitude = models.FloatField()
    altitude_m = models.FloatField(null=True, blank=True)
    raw_metadata = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "external_id"], name="unique_station_per_source")
        ]
        indexes = [models.Index(fields=["latitude", "longitude"])]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.source.slug}/{self.external_id})"


class Reading(models.Model):
    class ReadingType(models.TextChoices):
        CHUVA_MM = "chuva_mm", "Chuva acumulada (mm)"
        NIVEL_M = "nivel_m", "Nível do rio (m)"
        TEMPERATURA_C = "temperatura_c", "Temperatura (°C)"
        UMIDADE_PCT = "umidade_pct", "Umidade relativa (%)"
        VENTO_MS = "vento_ms", "Vento (m/s)"
        VENTO_RAJADA_MS = "vento_rajada_ms", "Rajada de vento (m/s)"
        VENTO_DIR_GRAUS = "vento_dir_graus", "Direção do vento (graus)"
        MARE_M = "mare_m", "Maré (m)"

    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name="readings")
    reading_type = models.CharField(max_length=20, choices=ReadingType.choices)
    value = models.FloatField()
    timestamp = models.DateTimeField(help_text="Sempre em UTC.")
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["station", "reading_type", "timestamp"], name="unique_reading_per_station_type_time"
            )
        ]
        indexes = [models.Index(fields=["station", "reading_type", "-timestamp"])]
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.station.name} · {self.get_reading_type_display()} = {self.value} @ {self.timestamp:%Y-%m-%d %H:%M}"


class AlertRule(models.Model):
    class Comparison(models.TextChoices):
        GTE = "gte", "Maior ou igual a"
        LTE = "lte", "Menor ou igual a"

    class Severity(models.TextChoices):
        ATENCAO = "atencao", "Atenção"
        ALERTA = "alerta", "Alerta"
        ALERTA_MAXIMO = "alerta_maximo", "Alerta máximo"

    name = models.CharField(max_length=150)
    reading_type = models.CharField(max_length=20, choices=Reading.ReadingType.choices)
    comparison = models.CharField(max_length=3, choices=Comparison.choices, default=Comparison.GTE)
    threshold_value = models.FloatField()
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.ATENCAO)
    station = models.ForeignKey(
        Station, on_delete=models.CASCADE, related_name="alert_rules", null=True, blank=True,
        help_text="Deixe em branco para aplicar a regra a todas as estações do tipo de leitura.",
    )
    municipality = models.CharField(max_length=120, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-severity", "name"]

    def __str__(self):
        alvo = self.station.name if self.station else (self.municipality or "todas as estações")
        return f"{self.name} ({alvo})"

    def is_triggered_by(self, value: float) -> bool:
        if self.comparison == self.Comparison.GTE:
            return value >= self.threshold_value
        return value <= self.threshold_value


class AlertEvent(models.Model):
    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name="events")
    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name="alert_events")
    reading = models.ForeignKey(Reading, on_delete=models.SET_NULL, null=True, blank=True)
    value = models.FloatField()
    triggered_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-triggered_at"]

    @property
    def active(self) -> bool:
        return self.resolved_at is None

    def __str__(self):
        estado = "ativo" if self.active else "resolvido"
        return f"{self.rule.name} · {self.station.name} · {estado}"
