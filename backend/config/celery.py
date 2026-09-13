import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("cemaden_rj_painel")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Cadência de coleta por fonte — ajustar conforme limites de cada API.
app.conf.beat_schedule = {
    "ingest-inmet-a-cada-15-min": {
        "task": "ingestion.tasks.ingest_source",
        "schedule": crontab(minute="*/15"),
        "args": ("inmet",),
    },
    "ingest-cemaden-nacional-a-cada-15-min": {
        "task": "ingestion.tasks.ingest_source",
        "schedule": crontab(minute="*/15"),
        "args": ("cemaden_nacional",),
    },
    "ingest-alerta-rio-a-cada-15-min": {
        "task": "ingestion.tasks.ingest_source",
        "schedule": crontab(minute="*/15"),
        "args": ("alerta_rio",),
    },
}
