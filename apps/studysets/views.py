from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.exceptions import GenerationError
from apps.common.permissions import IsOwner
from apps.common.throttles import GenerationThrottle
from apps.subscriptions.services import assert_can_generate

from .models import QuizQuestion, StudySet
from .serializers import (
    QuizQuestionSerializer,
    StudySetCreateSerializer,
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

    def get_queryset(self):
        # Object-level isolation: a user only ever sees their own sets.
        # prefetch keeps the library list O(1) queries (no N+1 on quiz/words).
        return StudySet.objects.filter(owner=self.request.user).prefetch_related(
            "quiz", "word_game"
        )

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

    @action(detail=True, methods=["post"], url_path="quiz-pack")
    def quiz_pack(self, request, pk=None):
        """Generate and persist a fresh batch of quiz items distinct from
        the ones already on this study set. Body: {"count": int (default 10)}.
        Returns the newly created QuizQuestion rows.
        """
        from apps.generation.llm import generate_extra_quiz

        study_set = self.get_object()
        try:
            count = int(request.data.get("count", 10) or 10)
        except (TypeError, ValueError):
            count = 10
        count = max(3, min(count, 20))

        # Build the source text from whatever fuller content we have on disk.
        sections = study_set.sections or []
        chunks = []
        for sec in sections:
            content = (sec.get("content") or "").strip()
            if content:
                chunks.append(f"## {sec.get('title') or ''}\n{content}")
        source_text = "\n\n".join(chunks) or (study_set.summary or "")
        if not source_text.strip():
            return Response(
                {"detail": "This study set has no readable content to draw from."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing_prompts = list(study_set.quiz.values_list("prompt", flat=True))
        try:
            new_items = generate_extra_quiz(
                source_text=source_text,
                exclude_prompts=existing_prompts,
                n=count,
                topic="Fresh",
            )
        except GenerationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        next_order = (study_set.quiz.count() or 0)
        created = []
        with transaction.atomic():
            for i, q in enumerate(new_items):
                created.append(
                    QuizQuestion.objects.create(
                        study_set=study_set,
                        prompt=q["prompt"],
                        choices=q["choices"],
                        correct_index=q["correct_index"],
                        explanation=q.get("explanation", ""),
                        topic=q.get("topic", "Fresh"),
                        difficulty=q.get("difficulty", "medium"),
                        order=next_order + i,
                    )
                )

        return Response(
            QuizQuestionSerializer(created, many=True).data,
            status=status.HTTP_201_CREATED,
        )


def _enqueue(study_set_id):
    from django.conf import settings

    from apps.generation.tasks import generate_study_set

    # In dev we run with CELERY_TASK_ALWAYS_EAGER=True so .delay() blocks the
    # caller until the task finishes. That would block the POST request for
    # the entire LLM round-trip and trip the client's receiveTimeout. Push it
    # onto a background thread so the view returns 202 immediately.
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        import threading

        threading.Thread(
            target=lambda: generate_study_set.delay(str(study_set_id)),
            daemon=True,
        ).start()
    else:
        generate_study_set.delay(str(study_set_id))
