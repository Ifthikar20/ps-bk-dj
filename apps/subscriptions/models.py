from django.conf import settings
from django.db import models


class Subscription(models.Model):
    class Platform(models.TextChoices):
        APPLE = "apple", "Apple"
        GOOGLE = "google", "Google"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    is_premium = models.BooleanField(default=False)
    usage_count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    platform = models.CharField(
        max_length=12, choices=Platform.choices, null=True, blank=True
    )
    original_txn_id = models.CharField(
        max_length=255, null=True, blank=True, db_index=True
    )

    def __str__(self):
        return f"{self.user.email}: {'premium' if self.is_premium else 'free'}"
