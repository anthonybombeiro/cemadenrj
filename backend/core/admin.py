from django.contrib import admin

from .models import AlertEvent, AlertRule, Reading, Source, Station


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "enabled", "last_ingested_at")
    list_filter = ("enabled",)
    readonly_fields = ("last_ingested_at", "last_ingest_error")


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ("name", "source", "external_id", "municipality", "station_type", "status", "updated_at")
    list_filter = ("source", "station_type", "status", "municipality")
    search_fields = ("name", "external_id", "municipality")


@admin.register(Reading)
class ReadingAdmin(admin.ModelAdmin):
    list_display = ("station", "reading_type", "value", "timestamp")
    list_filter = ("reading_type", "station__source")
    date_hierarchy = "timestamp"
    search_fields = ("station__name",)


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "reading_type", "comparison", "threshold_value", "severity", "station", "municipality", "active")
    list_filter = ("severity", "active", "reading_type")


@admin.register(AlertEvent)
class AlertEventAdmin(admin.ModelAdmin):
    list_display = ("rule", "station", "value", "triggered_at", "resolved_at")
    list_filter = ("rule__severity",)
    date_hierarchy = "triggered_at"
