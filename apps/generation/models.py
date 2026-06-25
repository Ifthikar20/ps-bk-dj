from django.conf import settings
from django.db import models


class TokenUsage(models.Model):
    """One row per LLM call, attributing token spend to a user.

    Lets us report per-user token consumption (and cost) over time.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="token_usages",
    )
    study_set = models.ForeignKey(
        "studysets.StudySet",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="token_usages",
    )
    provider = models.CharField(max_length=32)
    model = models.CharField(max_length=64)
    purpose = models.CharField(max_length=32, default="generation")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"])]

    def save(self, *args, **kwargs):
        self.total_tokens = (self.input_tokens or 0) + (self.output_tokens or 0)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user_id} {self.model} {self.total_tokens}tok"
