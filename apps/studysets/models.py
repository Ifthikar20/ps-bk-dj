from django.conf import settings
from django.db import models

from apps.common.models import UUIDModel


class StudySet(UUIDModel):
    """One row = one generated bundle (the Dart `LearningMaterial`)."""

    class SourceKind(models.TextChoices):
        LINK = "link", "Link"
        FILE = "file", "File"
        TEXT = "text", "Text"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="study_sets",
    )
    title = models.CharField(max_length=255, blank=True, default="")
    source_kind = models.CharField(max_length=8, choices=SourceKind.choices)
    source_ref = models.TextField()
    summary = models.TextField(blank=True, default="")
    key_points = models.JSONField(default=list)
    topics = models.JSONField(default=list)
    # Sectioned study content: [{title, content, example, quiz:[...]}].
    sections = models.JSONField(default=list)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )
    error = models.TextField(blank=True, default="")

    # Idempotency: a retried POST with the same key returns the same set.
    idempotency_key = models.CharField(
        max_length=128, null=True, blank=True, db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["owner", "-created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "idempotency_key"],
                name="unique_owner_idempotency_key",
                condition=models.Q(idempotency_key__isnull=False),
            )
        ]

    def __str__(self):
        return self.title or f"StudySet {self.id}"


class QuizQuestion(UUIDModel):
    class Difficulty(models.TextChoices):
        EASY = "easy", "Easy"
        MEDIUM = "medium", "Medium"
        HARD = "hard", "Hard"

    study_set = models.ForeignKey(
        StudySet, on_delete=models.CASCADE, related_name="quiz"
    )
    prompt = models.TextField()
    choices = models.JSONField()
    correct_index = models.PositiveSmallIntegerField()
    explanation = models.TextField(null=True, blank=True)
    topic = models.CharField(max_length=120, default="General")
    difficulty = models.CharField(
        max_length=8, choices=Difficulty.choices, default=Difficulty.MEDIUM
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order",)


class WordChallenge(UUIDModel):
    study_set = models.ForeignKey(
        StudySet, on_delete=models.CASCADE, related_name="word_game"
    )
    word = models.CharField(max_length=64)
    clue = models.TextField()
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order",)
