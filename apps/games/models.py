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
    """A server-published, S3-hosted web game.

    Adding a row here (plus uploading the game's web bundle to the games CDN)
    publishes a new game to every client — iOS and web — without an app
    release: the app fetches the manifest and registers each enabled row at
    startup. ``key`` is the stable client-side id; ``slug`` is the path segment
    loaded from the games base URL as ``{gamesBaseUrl}/games/<slug>/index.html``.
    """

    class Difficulty(models.TextChoices):
        EASY = "easy", "Easy"
        MEDIUM = "medium", "Medium"
        HARD = "hard", "Hard"

    class Audience(models.TextChoices):
        STABLE = "stable", "Stable"
        BETA = "beta", "Beta"

    key = models.SlugField(
        max_length=64,
        unique=True,
        help_text="Stable client id (LearningGame.id). Keep it unique across "
        "all games, e.g. 'quiz_rush'.",
    )
    slug = models.SlugField(
        max_length=64,
        help_text="Path segment under the games base URL: "
        "{gamesBaseUrl}/games/<slug>/<version>/index.html",
    )
    version = models.SlugField(
        max_length=32,
        default="1",
        help_text="Immutable bundle version, used as a path segment "
        "(.../<slug>/<version>/). Bump it to deploy; point back to roll back.",
    )
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=200)
    icon = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Material icon name (e.g. 'bolt'). Falls back to emoji, then "
        "a generic game icon, if unknown to the client.",
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
    sdk_version = models.PositiveSmallIntegerField(
        default=1,
        help_text="PlayStudy SDK version this bundle targets. Clients hide "
        "games whose sdkVersion is newer than the app supports.",
    )
    max_score = models.PositiveIntegerField(
        default=0,
        help_text="Server-side sanity cap on a play's score (0 = no cap). "
        "Guards leaderboards against tampered client-reported scores.",
    )
    audience = models.CharField(
        max_length=8,
        choices=Audience.choices,
        default=Audience.STABLE,
        db_index=True,
        help_text="'beta' games are only returned when the client asks for the "
        "beta channel — use it to canary a game before going stable.",
    )

    class Meta:
        ordering = ("sort_order", "name")

    def __str__(self):
        return f"{self.name} ({self.key}@{self.version})"

    def clean(self):
        # Surface "0xFFAABBCC" / "#RRGGBB" coercion errors in the admin rather
        # than as opaque 500s when the renderer serializes the manifest.
        super().clean()
        _validate_cover_colors(self.cover_colors)
        _validate_requires(self.requires)


class GameSession(UUIDModel, TimeStampedModel):
    """One play of a game by a user — the server-owned record of "games I play".

    Platform-agnostic: a play in the iOS WebView or the web iframe reports the
    same events here, so play history, save-state (resume) and scores live on
    the server. A score earned on one platform therefore reflects on the other.
    The game is referenced by its stable registry key (matching ``Game.key``)
    rather than a FK, so history survives a game being removed from the catalog.
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
        help_text="Stable registry id of the game (LearningGame.id / Game.key).",
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


class GameTelemetry(TimeStampedModel):
    """Lightweight signal from the game host so a broken remote bundle is
    visible without waiting for user complaints. Since games are pushed to S3
    with no review, this is the main way to learn that one failed to load or
    threw at runtime.
    """

    class Kind(models.TextChoices):
        LOADED = "loaded", "Loaded"
        LOAD_FAILED = "load_failed", "Load failed"
        ERROR = "error", "Runtime error"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="game_telemetry",
        null=True,
        blank=True,
    )
    game_key = models.SlugField(max_length=64, db_index=True)
    version = models.SlugField(max_length=32, blank=True, default="")
    kind = models.CharField(max_length=12, choices=Kind.choices, db_index=True)
    message = models.CharField(max_length=500, blank=True, default="")
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["game_key", "kind", "-created_at"])]

    def __str__(self):
        return f"{self.game_key} · {self.kind}"


class GameToggle(TimeStampedModel):
    """A simple on/off switch for ANY game, by its stable client key.

    This is how the native, in-app games (Flappy, the space shooters, the
    crossword, …) — which are NOT in the hosted ``Game`` catalog — get turned
    on and off without an app release. The app fetches these flags at startup
    and unregisters any key marked disabled (a remote kill-switch).

    ``key`` matches ``LearningGame.id`` on the client (e.g. ``flappy_web``). A
    missing row means "enabled" (fail-open), so you only need a row for a game
    you actually want to be able to toggle. Hosted web games are normally
    switched via ``Game.enabled`` instead — but a disabled flag here overrides
    them too, so this doubles as a catch-all kill-switch.
    """

    key = models.SlugField(
        max_length=64,
        unique=True,
        help_text="Stable client id (LearningGame.id), e.g. 'flappy_web'.",
    )
    label = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text="Friendly name shown in this list, e.g. 'Flappy Pip'.",
    )
    enabled = models.BooleanField(default=True, db_index=True)
    note = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Optional reason for the current state, for your reference.",
    )

    class Meta:
        ordering = ("label", "key")

    def __str__(self):
        return f"{self.label or self.key} ({'on' if self.enabled else 'OFF'})"
