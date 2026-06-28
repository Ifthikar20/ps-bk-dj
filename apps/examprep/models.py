from django.conf import settings
from django.db import models

from apps.common.models import UUIDModel
from apps.studysets.models import StudySet


class ExamPlan(UUIDModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        GENERATING = "generating", "Generating"
        PROPOSED = "proposed", "Proposed"  # guide generated, awaiting approval
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exam_plans"
    )
    study_set = models.ForeignKey(StudySet, on_delete=models.CASCADE)
    material_title = models.CharField(max_length=255)
    exam_title = models.CharField(max_length=255)
    exam_date = models.DateField()
    questions_per_day = models.PositiveSmallIntegerField()
    topics = models.JSONField(default=list)

    # Guide / spaced-repetition state. Legacy/mobile plans default to ACTIVE so
    # they remain immediately playable; the web guide flow starts as DRAFT.
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    excluded_topics = models.JSONField(default=list)
    # 0.5 / 1.0 / 1.5 / 2.0 — scales questions_per_day.
    frequency_multiplier = models.FloatField(default=1.0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["owner", "-created_at"])]


class PlanDay(models.Model):
    """One scheduled study day: a section to read + the questions to answer."""

    plan = models.ForeignKey(ExamPlan, on_delete=models.CASCADE, related_name="days")
    ymd = models.CharField(max_length=10)
    day_index = models.PositiveIntegerField()
    section_index = models.PositiveIntegerField(default=0)
    section_title = models.CharField(max_length=255, blank=True, default="")
    question_ids = models.JSONField(default=list)

    class Meta:
        ordering = ("day_index",)
        constraints = [
            models.UniqueConstraint(fields=["plan", "ymd"], name="unique_plan_day")
        ]
        indexes = [models.Index(fields=["plan", "ymd"])]


class WrongAnswerCard(models.Model):
    """A Leitner spaced-repetition card for a missed question."""

    plan = models.ForeignKey(ExamPlan, on_delete=models.CASCADE, related_name="cards")
    question_id = models.UUIDField()
    topic = models.CharField(max_length=120, default="General")
    box = models.PositiveSmallIntegerField(default=1)  # 1..5
    due_ymd = models.CharField(max_length=10)
    times_wrong = models.PositiveIntegerField(default=0)
    times_right = models.PositiveIntegerField(default=0)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "question_id"], name="unique_plan_card"
            )
        ]
        indexes = [models.Index(fields=["plan", "resolved", "due_ymd"])]


class PlanReminder(models.Model):
    """A nudge to study (in-app now; emailed_at is a hook for future email)."""

    plan = models.ForeignKey(
        ExamPlan, on_delete=models.CASCADE, related_name="reminders"
    )
    ymd = models.CharField(max_length=10)
    kind = models.CharField(max_length=16, default="daily")  # daily | deadline_soon
    message = models.CharField(max_length=255, blank=True, default="")
    emailed_at = models.DateTimeField(null=True, blank=True)
    dismissed = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "ymd", "kind"], name="unique_plan_reminder"
            )
        ]
        indexes = [models.Index(fields=["plan", "ymd"])]


class DailyResult(models.Model):
    plan = models.ForeignKey(
        ExamPlan, on_delete=models.CASCADE, related_name="results"
    )
    ymd = models.CharField(max_length=10)
    correct = models.PositiveSmallIntegerField()
    total = models.PositiveSmallIntegerField()
    completed = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "ymd"], name="unique_plan_day_result"
            )
        ]
