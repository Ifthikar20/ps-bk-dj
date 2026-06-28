from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    GameFlagsView,
    GameListView,
    GameSessionViewSet,
    GameTelemetryView,
    GameToggleViewSet,
)

router = DefaultRouter()
router.register("games/sessions", GameSessionViewSet, basename="game-session")
router.register("games/toggles", GameToggleViewSet, basename="game-toggle")

urlpatterns = [
    path("games/", GameListView.as_view(), name="games"),
    path("games/flags/", GameFlagsView.as_view(), name="game-flags"),
    path("games/telemetry/", GameTelemetryView.as_view(), name="game-telemetry"),
] + router.urls
