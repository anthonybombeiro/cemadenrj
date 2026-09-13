from rest_framework.routers import DefaultRouter

from .views import AlertEventViewSet, SourceViewSet, StationViewSet

router = DefaultRouter()
router.register("sources", SourceViewSet, basename="source")
router.register("stations", StationViewSet, basename="station")
router.register("alerts", AlertEventViewSet, basename="alert")

urlpatterns = router.urls
