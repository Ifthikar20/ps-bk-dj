from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.permissions import IsOwner

from .models import DailyResult, ExamPlan
from .serializers import ExamPlanSerializer, SessionSerializer


class ExamPlanViewSet(viewsets.ModelViewSet):
    permission_classes = [IsOwner]
    serializer_class = ExamPlanSerializer

    def get_queryset(self):
        return ExamPlan.objects.filter(owner=self.request.user).prefetch_related(
            "results"
        )

    @action(detail=True, methods=["post"])
    def sessions(self, request, pk=None):
        """Record a daily result (upsert) and fire the daily-session reward."""
        plan = self.get_object()
        serializer = SessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        DailyResult.objects.update_or_create(
            plan=plan,
            ymd=data["day"],
            defaults={
                "correct": data["correct"],
                "total": data["total"],
                "completed": True,
            },
        )

        # Award the daily-session reward server-side, idempotent per plan+day,
        # so re-opening the same day can't repeatedly mint points.
        from apps.rewards.services import award

        award(
            request.user,
            reason="Daily exam session",
            context={"correct": data["correct"], "total": data["total"]},
            dedupe_key=f"examsession:{plan.id}:{data['day']}",
        )

        plan.refresh_from_db()
        return Response(ExamPlanSerializer(plan, context={"request": request}).data)
