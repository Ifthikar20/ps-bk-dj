from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import GameListView, GameSessionViewSet

router = DefaultRouter()
router.register("games/sessions", GameSessionViewSet, basename="game-session")

urlpatterns = [
    path("games/", GameListView.as_view(), name="games"),
] + router.urls
