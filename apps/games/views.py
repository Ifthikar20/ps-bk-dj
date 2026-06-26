from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsOwner

from .models import Game, GameSession, GameTelemetry, GameToggle
from .serializers import (
    GameSerializer,
    GameSessionSerializer,
    GameSessionStartSerializer,
    GameSessionUpdateSerializer,
    GameTelemetrySerializer,
    GameToggleSerializer,
)


class GameListView(ListAPIView):
    """GET /games — the public catalog of S3-hosted web games.

    Returns only enabled games, in admin order. Non-sensitive catalog data the
    app registers at startup, so it is intentionally unauthenticated (like
    /health), overriding the project-wide IsAuthenticated default. Version
    gating (min_app_version / sdk_version) is left to the client so one manifest
    serves every app version, iOS and web alike.

    Channels: stable by default; ``?channel=beta`` also returns beta games so a
    new bundle can be canaried before promoting it to stable.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = GameSerializer
    pagination_class = None  # small, fully-cached list — return it whole

    def get_queryset(self):
        qs = Game.objects.filter(enabled=True)
        if self.request.query_params.get("channel") != "beta":
            qs = qs.filter(audience=Game.Audience.STABLE)
        return qs


class GameFlagsView(ListAPIView):
    """GET /games/flags — per-game on/off switches the app applies at startup.

    Unauthenticated catalog data like /games. Returns every GameToggle row; the
    client enables games by default and only acts on rows marked
    ``enabled: false`` — a remote kill-switch that can pull any game, including
    a native (in-app) one, with no app release. Fail-open by design: if this
    can't be reached the client keeps whatever games it already has.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = GameToggleSerializer
    pagination_class = None  # tiny list — return it whole

    def get_queryset(self):
        return GameToggle.objects.all()


class GameTelemetryView(APIView):
    """POST /games/telemetry — record a load/error signal from the game host.

    Games ship to S3 with no review, so this is how a broken bundle becomes
    visible. Best-effort and cheap; failures here never affect gameplay.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = GameTelemetrySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        GameTelemetry.objects.create(
            user=request.user,
            game_key=v["game_key"],
            version=v.get("version", ""),
            kind=v["kind"],
            message=v.get("message", ""),
            context=v.get("context", {}),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class GameSessionViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Server-owned play records ("games I play"). Any game reports its play
    here; native (Flame) games start on open and complete on close:

      POST   /games/sessions/                 start a play  -> {id, ...}
      PATCH  /games/sessions/{id}/            heartbeat: score / save-state
      POST   /games/sessions/{id}/complete/   finalize (status + final score)
      GET    /games/sessions/                 my history (?gameKey= &status=)
      GET    /games/sessions/{id}/            one play (resume save-state)

    Points are NOT minted here — gameplay rewards continue to flow through the
    rewards engine (`/rewards/activity`) on the real in-game event. This keeps a
    single, forgery-resistant source of points and avoids rewarding a bare
    open/close.
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
        session = GameSession.objects.create(
            user=request.user,
            game_key=data.validated_data["game_key"],
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
        """Finalize a play (idempotent): record the final score and close it."""
        session = self.get_object()
        if session.status != GameSession.Status.COMPLETED:
            body = GameSessionUpdateSerializer(data=request.data)
            body.is_valid(raise_exception=True)
            self._apply(session, body.validated_data)
            # Sanity-cap the client-reported score against the game's max so a
            # tampered bundle can't post an absurd score to the leaderboard.
            cap = (
                Game.objects.filter(key=session.game_key)
                .values_list("max_score", flat=True)
                .first()
            )
            if cap:
                session.score = min(session.score, cap)
            session.status = GameSession.Status.COMPLETED
            session.completed_at = timezone.now()
            session.save(
                update_fields=[
                    "score",
                    "progress",
                    "status",
                    "completed_at",
                    "updated_at",
                ]
            )
        return Response(GameSessionSerializer(session).data)

    @staticmethod
    def _apply(session, validated):
        if "score" in validated:
            session.score = validated["score"]
        if "progress" in validated:
            session.progress = validated["progress"]
