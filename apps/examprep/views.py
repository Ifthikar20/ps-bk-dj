from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.permissions import IsOwner

from . import services
from .models import DailyResult, ExamPlan
from .serializers import (
    ExamPlanSerializer,
    SessionSerializer,
    SettingsSerializer,
)


def _conflict(message, code="invalid_state"):
    return Response(
        {"error": {"code": code, "message": message}},
        status=status.HTTP_409_CONFLICT,
    )


def _days_summary(plan):
    return [
        {
            "ymd": d.ymd,
            "day_index": d.day_index,
            "section_index": d.section_index,
            "section_title": d.section_title,
            "question_count": len(d.question_ids or []),
        }
        for d in plan.days.all()
    ]


class ExamPlanViewSet(viewsets.ModelViewSet):
    permission_classes = [IsOwner]
    serializer_class = ExamPlanSerializer

    def get_queryset(self):
        return ExamPlan.objects.filter(owner=self.request.user).prefetch_related(
            "results", "days"
        )

    def _plan_response(self, plan):
        return Response(
            ExamPlanSerializer(plan, context={"request": self.request}).data
        )

    # ---- guide lifecycle --------------------------------------------------- #
    @action(detail=True, methods=["post"])
    def generate(self, request, pk=None):
        """Build (or rebuild) the proposed day-by-day study guide."""
        plan = self.get_object()
        if plan.status not in (ExamPlan.Status.DRAFT, ExamPlan.Status.PROPOSED):
            return _conflict("Only a draft plan can be (re)generated.")
        services.build_schedule(plan)
        plan.status = ExamPlan.Status.PROPOSED
        plan.save(update_fields=["status"])
        data = ExamPlanSerializer(plan, context={"request": request}).data
        data["days"] = _days_summary(plan)
        return Response(data)

    @action(detail=True, methods=["get"])
    def schedule(self, request, pk=None):
        """The proposed/active day-by-day plan (for the review + dashboard map)."""
        plan = self.get_object()
        return Response(
            {
                "status": plan.status,
                "exam_title": plan.exam_title,
                "exam_date": plan.exam_date,
                "material_title": plan.material_title,
                "days": _days_summary(plan),
            }
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """Approve a proposed guide -> the plan becomes active."""
        plan = self.get_object()
        if plan.status != ExamPlan.Status.PROPOSED:
            return _conflict("Only a proposed plan can be approved.")
        plan.status = ExamPlan.Status.ACTIVE
        plan.approved_at = timezone.now()
        plan.save(update_fields=["status", "approved_at"])
        services.create_reminders(plan)
        return self._plan_response(plan)

    # ---- daily session ----------------------------------------------------- #
    @action(detail=True, methods=["get"])
    def today(self, request, pk=None):
        plan = self.get_object()
        day = services.get_active_day(plan)
        return Response(services.serialize_day(plan, day))

    @action(detail=True, methods=["get"], url_path=r"days/(?P<ymd>[0-9-]+)")
    def day(self, request, pk=None, ymd=None):
        plan = self.get_object()
        d = plan.days.filter(ymd=ymd).first()
        return Response(services.serialize_day(plan, d))

    @action(detail=True, methods=["post"])
    def sessions(self, request, pk=None):
        """Record a daily result (upsert), update the Leitner bucket, and fire
        the daily-session reward."""
        plan = self.get_object()
        if plan.status != ExamPlan.Status.ACTIVE:
            return _conflict("This plan isn't active yet.")
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

        services.apply_session_results(
            plan,
            data["day"],
            data.get("wrong_question_ids") or [],
            data.get("correct_question_ids") or [],
        )

        from apps.rewards.services import award

        award(
            request.user,
            reason="Daily exam session",
            context={"correct": data["correct"], "total": data["total"]},
            dedupe_key=f"examsession:{plan.id}:{data['day']}",
        )

        services.maybe_complete(plan)
        plan.refresh_from_db()
        return self._plan_response(plan)

    # ---- settings ---------------------------------------------------------- #
    @action(detail=True, methods=["get", "patch"], url_path="settings")
    def plan_settings(self, request, pk=None):
        plan = self.get_object()
        if request.method.lower() == "patch":
            ser = SettingsSerializer(data=request.data)
            ser.is_valid(raise_exception=True)
            v = ser.validated_data
            fields = []
            if "frequency_multiplier" in v:
                plan.frequency_multiplier = v["frequency_multiplier"]
                fields.append("frequency_multiplier")
            if "excluded_topics" in v:
                plan.excluded_topics = v["excluded_topics"]
                fields.append("excluded_topics")
            if "questions_per_day" in v:
                plan.questions_per_day = v["questions_per_day"]
                fields.append("questions_per_day")
            if fields:
                plan.save(update_fields=fields)
            # Reschedule future days only so past progress is preserved.
            if plan.status == ExamPlan.Status.ACTIVE:
                services.build_schedule(plan, future_only=True)
                services.create_reminders(plan)
        return Response(
            {
                "frequency_multiplier": plan.frequency_multiplier,
                "excluded_topics": plan.excluded_topics,
                "questions_per_day": plan.questions_per_day,
            }
        )

    # ---- reminders --------------------------------------------------------- #
    @action(detail=False, methods=["get"], url_path="reminders/today")
    def reminders_today(self, request):
        """Cross-plan nudges for today: unfinished sessions + due reviews."""
        out = []
        plans = ExamPlan.objects.filter(
            owner=request.user, status=ExamPlan.Status.ACTIVE
        ).prefetch_related("days", "results", "cards")
        for plan in plans:
            today = services.user_today(plan.owner).isoformat()
            has_today = plan.days.filter(ymd=today).exists()
            session_done = plan.results.filter(ymd=today).exists()
            due_review = plan.cards.filter(
                resolved=False, due_ymd__lte=today
            ).count()
            if (has_today and not session_done) or due_review:
                out.append(
                    {
                        "plan_id": str(plan.id),
                        "plan_title": plan.exam_title,
                        "ymd": today,
                        "session_done": session_done,
                        "due_review": due_review,
                        "days_left": (plan.exam_date - services.user_today(plan.owner)).days,
                    }
                )
        return Response({"results": out})

    @action(
        detail=True, methods=["patch"], url_path=r"reminders/(?P<ymd>[0-9-]+)"
    )
    def reminder(self, request, pk=None, ymd=None):
        plan = self.get_object()
        r = plan.reminders.filter(ymd=ymd).first()
        if r is not None:
            r.dismissed = bool(request.data.get("dismissed", True))
            r.save(update_fields=["dismissed"])
        return Response({"ok": True})
