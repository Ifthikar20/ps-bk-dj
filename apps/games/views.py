from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny

from .models import Game
from .serializers import GameSerializer


class GameListView(ListAPIView):
    """GET /games — the public catalog of server-published web games.

    Returns only enabled games, in admin-defined order. This is non-sensitive
    catalog data (no user scoping) and the app registers it at startup, so it
    is intentionally unauthenticated like /health, overriding the project-wide
    IsAuthenticated default. Version gating (min_app_version) is left to the
    client so a single manifest serves every app version.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = GameSerializer
    pagination_class = None  # small, fully-cached list — return it whole

    def get_queryset(self):
        return Game.objects.filter(enabled=True)
