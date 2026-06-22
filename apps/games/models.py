from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


def _validate_cover_colors(value):
    """cover_colors must be a list of 0xAARRGGBB / #RRGGBB style hex strings.

    The client parses each entry straight into a Dart Color, so a malformed
    value would surface as a render error in the app. Validate here instead.
    """
    if not isinstance(value, list) or not value:
        raise ValidationError("coverColors must be a non-empty list of hex strings.")
    for c in value:
        if not isinstance(c, str):
            raise ValidationError("Each cover color must be a string.")


def _validate_requires(value):
    """requires is a flat {field: minCount} map the client evaluates against a
    study set (e.g. {"quiz": 1} or {"words": 2}). Keys are limited to the
    material collections a game can gate on; values must be positive ints.
    """
    if not isinstance(value, dict):
        raise ValidationError('requires must be an object, e.g. {"quiz": 1}.')
    allowed = {"quiz", "words"}
    for key, count in value.items():
        if key not in allowed:
            raise ValidationError(
                f'Unsupported requires key "{key}". Allowed: {sorted(allowed)}.'
            )
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValidationError(f'requires["{key}"] must be a positive integer.')


class Game(UUIDModel, TimeStampedModel):
    """A server-published, web-hosted mini-game.

    Adding a row here (plus uploading the game's HTML bundle to the games CDN)
    publishes a new game to every client without an app release: the app
    fetches the manifest at startup and registers one ``RemoteWebGame`` per
    enabled row. ``key`` is the stable client-side id (routing / analytics /
    save-state); ``slug`` is the path segment loaded from the games base URL
    as ``{gamesBaseUrl}/games/<slug>/index.html``.
    """

    class Difficulty(models.TextChoices):
        EASY = "easy", "Easy"
        MEDIUM = "medium", "Medium"
        HARD = "hard", "Hard"

    key = models.SlugField(
        max_length=64,
        unique=True,
        help_text="Stable client id (LearningGame.id). Avoid colliding with "
        "built-in native game ids, e.g. use 'flappy_remote' not 'flappy_web'.",
    )
    slug = models.SlugField(
        max_length=64,
        help_text="Path segment under the games base URL: "
        "{gamesBaseUrl}/games/<slug>/index.html",
    )
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=200)
    icon = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Material icon name (e.g. 'flutter_dash'). Falls back to "
        "emoji, then a generic game icon, if unknown to the client.",
    )
    emoji = models.CharField(max_length=8, blank=True, default="")
    cover_colors = models.JSONField(
        default=list,
        validators=[_validate_cover_colors],
        help_text='Two-stop gradient, e.g. ["0xFFFBC78A", "0xFFEF4444"].',
    )
    difficulty = models.CharField(
        max_length=6, choices=Difficulty.choices, default=Difficulty.MEDIUM
    )
    requires = models.JSONField(
        default=dict,
        blank=True,
        validators=[_validate_requires],
        help_text='Data-driven canPlay rule, e.g. {"quiz": 1} or {"words": 2}. '
        "Empty means the game is always available.",
    )
    min_app_version = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="Hide from clients older than this semver (e.g. '1.4.0'). "
        "Blank means no minimum.",
    )
    enabled = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(
        default=0, help_text="Lower sorts first; ties broken by name."
    )

    class Meta:
        ordering = ("sort_order", "name")

    def __str__(self):
        return f"{self.name} ({self.key})"

    def clean(self):
        # Surface "0xFFAABBCC" / "#RRGGBB" coercion errors in the admin rather
        # than as opaque 500s when the renderer serializes the manifest.
        super().clean()
        _validate_cover_colors(self.cover_colors)
        _validate_requires(self.requires)


class GameSession(UUIDModel, TimeStampedModel):
    """One play of a game by a user — the server-owned record of "games I play".

    Unified across platforms: whether the game runs in the mobile WebView or a
    web iframe, the host forwards the same SDK events (progress / score /
    gameover) here, so play history, save-state (resume) and high scores live
    on the server, not in each client. Points are awarded through the
    server-authoritative rewards engine on completion (deduped per session), so
    a tampered client can't mint points.
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
    # Keep the catalog row for joins, but also snapshot the key so history
    # survives a game being disabled or deleted.
    game = models.ForeignKey(
        Game,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sessions",
    )
    game_key = models.SlugField(max_length=64, db_index=True)
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
    reward_points = models.PositiveIntegerField(
        default=0, help_text="Points granted on completion (by the rewards engine)."
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
