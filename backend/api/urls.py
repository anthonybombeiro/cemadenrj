from django.urls import path
from rest_framework.routers import DefaultRouter

from .admin_views import AdminOpsView
from .ingest_views import RemoteReadingsIngestView
from .views import AlertEventViewSet, RiskAlertViewSet, SourceViewSet, StationViewSet

router = DefaultRouter()
router.register("sources", SourceViewSet, basename="source")
router.register("stations", StationViewSet, basename="station")
router.register("alerts", AlertEventViewSet, basename="alert")
router.register("risk-alerts", RiskAlertViewSet, basename="risk-alert")

urlpatterns = [
    path("ingest/readings/", RemoteReadingsIngestView.as_view(), name="ingest-readings"),
    path("admin/run/", AdminOpsView.as_view(), name="admin-run"),
] + router.urls
