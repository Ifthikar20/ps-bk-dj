from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.common.permissions import IsOwner
from apps.rewards.serializers import RewardProfileSerializer
from apps.rewards.services import award

from .models import Game, GameSession
from .serializers import (
    GameSerializer,
    GameSessionSerializer,
    GameSessionStartSerializer,
    GameSessionUpdateSerializer,
)


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


class GameSessionViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Server-owned play records ("games I play"), unified across mobile and
    web. The game host (WebView or iframe) forwards SDK events here:

      POST   /games/sessions/                 start a play  -> {id, ...}
      PATCH  /games/sessions/{id}/            heartbeat: score / save-state
      POST   /games/sessions/{id}/complete/   finalize + award points
      GET    /games/sessions/                 my history (?gameKey= &status=)
      GET    /games/sessions/{id}/            one play (resume save-state)
    """

    permission_classes = [IsOwner, IsAuthenticated]
    serializer_class = GameSessionSerializer

    def get_queryset(self):
        qs = GameSession.objects.filter(user=self.request.user)
        game_key = self.request.query_params.get("gameKey")
        if game_key:
            qs = qs.filter(game_key=game_key)
        status_param = self.request.query_params.get("status")
        if status_param in GameSession.Status.values:
            qs = qs.filter(status=status_param)
        return qs

    def create(self, request, *args, **kwargs):
        data = GameSessionStartSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        key = data.validated_data["game_key"]
        session = GameSession.objects.create(
            user=request.user,
            game=Game.objects.filter(key=key).first(),
            game_key=key,
            study_set_id=data.validated_data.get("study_set_id"),
            progress=data.validated_data.get("progress", {}),
        )
        return Response(
            GameSessionSerializer(session).data, status=status.HTTP_201_CREATED
        )

    def partial_update(self, request, *args, **kwargs):
        """Heartbeat: persist the latest score / save-state mid-play."""
        session = self.get_object()
        if session.status != GameSession.Status.ACTIVE:
            return Response(
                {"detail": "This session is already closed."},
                status=status.HTTP_409_CONFLICT,
            )
        body = GameSessionUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        self._apply(session, body.validated_data)
        session.save(update_fields=["score", "progress", "updated_at"])
        return Response(GameSessionSerializer(session).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """Finalize a play and grant the (server-computed) completion reward.

        Idempotent: the reward is deduped on the session id, so a retried or
        duplicated complete call never double-awards points.
        """
        session = self.get_object()
        already_done = session.status == GameSession.Status.COMPLETED

        body = GameSessionUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        if not already_done:
            self._apply(session, body.validated_data)
            result = award(
                request.user,
                reason="Played a game",
                context={"score": session.score},
                dedupe_key=f"game_session:{session.id}",
            )
            session.reward_points = result["last_award"]
            session.status = GameSession.Status.COMPLETED
            session.completed_at = timezone.now()
            session.save(
                update_fields=[
                    "score",
                    "progress",
                    "reward_points",
                    "status",
                    "completed_at",
                    "updated_at",
                ]
            )
            profile = result["profile"]
        else:
            from apps.rewards.services import get_rewards_state

            profile = get_rewards_state(request.user)

        return Response(
            {
                "session": GameSessionSerializer(session).data,
                "rewards": RewardProfileSerializer(profile).data,
            }
        )

    @staticmethod
    def _apply(session, validated):
        if "score" in validated:
            session.score = validated["score"]
        if "progress" in validated:
            session.progress = validated["progress"]
