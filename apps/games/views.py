from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.permissions import IsOwner

from .models import GameSession
from .serializers import (
    GameSessionSerializer,
    GameSessionStartSerializer,
    GameSessionUpdateSerializer,
)


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
