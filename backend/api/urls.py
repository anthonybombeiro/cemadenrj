from django.urls import path
from rest_framework.routers import DefaultRouter

from .ingest_views import RemoteReadingsIngestView
from .views import AlertEventViewSet, SourceViewSet, StationViewSet

router = DefaultRouter()
router.register("sources", SourceViewSet, basename="source")
router.register("stations", StationViewSet, basename="station")
router.register("alerts", AlertEventViewSet, basename="alert")

urlpatterns = [
    path("ingest/readings/", RemoteReadingsIngestView.as_view(), name="ingest-readings"),
] + router.urls
