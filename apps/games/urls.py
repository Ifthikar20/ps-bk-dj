from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import GameListView, GameSessionViewSet, GameTelemetryView

router = DefaultRouter()
router.register("games/sessions", GameSessionViewSet, basename="game-session")

urlpatterns = [
    path("games/", GameListView.as_view(), name="games"),
    path("games/telemetry/", GameTelemetryView.as_view(), name="game-telemetry"),
] + router.urls
