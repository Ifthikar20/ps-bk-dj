from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


class GameSession(UUIDModel, TimeStampedModel):
    """One play of a game by a user — the server-owned record of "games I play".

    Engine-agnostic: a Flame (native) game records a play by starting a session
    when it opens and completing it when it closes, so play history, save-state
    (resume) and high scores live on the server, not in each client. The game is
    referenced by its stable registry key (LearningGame.id) rather than a FK, so
    history survives a game being removed from the app.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        ABANDONED = "abandoned", "Abandoned"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="game_sessions",
    )
    game_key = models.SlugField(
        max_length=64,
        db_index=True,
        help_text="Stable registry id of the game (LearningGame.id).",
    )
    study_set_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="Optional: the study set this play drew its content from.",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    score = models.PositiveIntegerField(default=0)
    progress = models.JSONField(
        default=dict, blank=True, help_text="Opaque save-state blob for resume."
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "game_key", "status"]),
        ]

    def __str__(self):
        return f"{self.user_id} · {self.game_key} · {self.status}"
