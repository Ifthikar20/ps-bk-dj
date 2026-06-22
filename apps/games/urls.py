from rest_framework.routers import DefaultRouter

from .views import GameSessionViewSet

router = DefaultRouter()
router.register("games/sessions", GameSessionViewSet, basename="game-session")

urlpatterns = router.urls
