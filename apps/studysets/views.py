from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.permissions import IsOwner
from apps.common.throttles import GenerationThrottle
from apps.subscriptions.services import assert_can_generate

from .models import StudySet
from .serializers import (
    StudySetCreateSerializer,
    StudySetListSerializer,
    StudySetSerializer,
    StudySetStatusSerializer,
)


class StudySetViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsOwner]
    serializer_class = StudySetSerializer

    def get_serializer_class(self):
        if self.action == "list":
            return StudySetListSerializer
        return StudySetSerializer

    def get_queryset(self):
        # Object-level isolation: a user only ever sees their own sets.
        qs = StudySet.objects.filter(owner=self.request.user)
        if self.action == "list":
            return qs  # list is lightweight — no quiz/word-game join needed
        return qs.prefetch_related("quiz", "word_game")

    def get_throttles(self):
        if self.action == "create":
            return [GenerationThrottle()]
        return super().get_throttles()

    def create(self, request, *args, **kwargs):
        """Create a study set and kick off async generation. Returns 202."""
        serializer = StudySetCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        idem_key = request.headers.get("Idempotency-Key")
        if idem_key:
            existing = StudySet.objects.filter(
                owner=request.user, idempotency_key=idem_key
            ).first()
            if existing is not None:
                return Response(
                    StudySetStatusSerializer(existing).data,
                    status=status.HTTP_200_OK,
                )

        # Gate generation server-side — never trust the client paywall.
        assert_can_generate(request.user)

        with transaction.atomic():
            study_set = StudySet.objects.create(
                owner=request.user,
                source_kind=data["source_kind"],
                source_ref=data["source_ref"],
                title=data.get("title", ""),
                status=StudySet.Status.PENDING,
                idempotency_key=idem_key or None,
            )
            # Enqueue only after the row is committed.
            transaction.on_commit(lambda: _enqueue(study_set.id))

        return Response(
            StudySetStatusSerializer(study_set).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        study_set = self.get_object()
        return Response(StudySetStatusSerializer(study_set).data)


def _enqueue(study_set_id):
    from apps.generation.tasks import generate_study_set

    generate_study_set.delay(str(study_set_id))
