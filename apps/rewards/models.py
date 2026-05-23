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
    """Audit log so points can't be forged client-side."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="point_events"
    )
    points = models.IntegerField()
    reason = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "-created_at"])]
