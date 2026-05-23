from django.conf import settings
from django.db import models

from apps.common.models import UUIDModel
from apps.studysets.models import StudySet


class ExamPlan(UUIDModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exam_plans"
    )
    study_set = models.ForeignKey(StudySet, on_delete=models.CASCADE)
    material_title = models.CharField(max_length=255)
    exam_title = models.CharField(max_length=255)
    exam_date = models.DateField()
    questions_per_day = models.PositiveSmallIntegerField()
    topics = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["owner", "-created_at"])]


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
