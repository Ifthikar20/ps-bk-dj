import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    class Provider(models.TextChoices):
        EMAIL = "email", "Email"
        APPLE = "apple", "Apple"
        GOOGLE = "google", "Google"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=120, blank=True, default="")
    avatar_url = models.URLField(null=True, blank=True)

    # Auth provider bookkeeping
    provider = models.CharField(
        max_length=16, choices=Provider.choices, default=Provider.EMAIL
    )
    provider_sub = models.CharField(max_length=255, null=True, blank=True, db_index=True)

    # Used by the rewards engine so "today" is correct per user.
    timezone = models.CharField(max_length=64, default="UTC")

    # Free-form client preferences (theme, dashboard flavor, reading font, etc.)
    # synced across every device. Web and mobile keys coexist in the same blob;
    # each client reads the keys it understands and ignores the rest.
    preferences = models.JSONField(default=dict, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_sub"],
                name="unique_provider_sub",
                condition=models.Q(provider_sub__isnull=False),
            )
        ]

    def __str__(self):
        return self.email
