from django.conf import settings
from django.db import models


class RewardProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rewards"
    )
    points = models.PositiveIntegerField(default=0)
    streak = models.PositiveIntegerField(default=0)
    last_active_ymd = models.CharField(max_length=10, null=True, blank=True)

    def __str__(self):
        return f"{self.user.email}: {self.points}pts / {self.streak}d"


class PointEvent(models.Model):
    """Audit log so points can't be forged client-side.

    ``dedupe_key`` makes server-awarded events idempotent: awarding the same
    real-world event twice (e.g. a retried generation, or re-opening the same
    exam day) is a no-op.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="point_events"
    )
    points = models.IntegerField()
    reason = models.CharField(max_length=64)
    dedupe_key = models.CharField(max_length=128, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "-created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "dedupe_key"],
                name="unique_user_dedupe_key",
                condition=models.Q(dedupe_key__isnull=False),
            )
        ]
