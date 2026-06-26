from django.contrib import admin

from .models import Game, GameSession, GameTelemetry, GameToggle


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "key",
        "slug",
        "version",
        "audience",
        "difficulty",
        "enabled",
        "sort_order",
    )
    list_filter = ("enabled", "audience", "difficulty")
    list_editable = ("enabled", "sort_order")
    search_fields = ("name", "key", "slug")
    readonly_fields = ("id", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("name", "key", "slug", "version", "description")}),
        ("Presentation", {"fields": ("icon", "emoji", "cover_colors", "difficulty")}),
        (
            "Gating",
            {
                "fields": (
                    "requires",
                    "min_app_version",
                    "sdk_version",
                    "max_score",
                    "audience",
                    "enabled",
                    "sort_order",
                )
            },
        ),
        ("Meta", {"fields": ("id", "created_at", "updated_at")}),
    )


@admin.register(GameToggle)
class GameToggleAdmin(admin.ModelAdmin):
    """One row per togglable game. Untick `enabled` + Save to pull a game
    (native or hosted) from every client — no app release required."""

    list_display = ("label", "key", "enabled", "note", "updated_at")
    list_editable = ("enabled", "note")
    list_filter = ("enabled",)
    search_fields = ("key", "label", "note")
    readonly_fields = ("created_at", "updated_at")


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = (
        "game_key",
        "user",
        "status",
        "score",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "game_key")
    search_fields = ("game_key", "user__email")
    readonly_fields = ("id", "created_at", "updated_at", "completed_at")


@admin.register(GameTelemetry)
class GameTelemetryAdmin(admin.ModelAdmin):
    list_display = ("game_key", "version", "kind", "message", "user", "created_at")
    list_filter = ("kind", "game_key")
    search_fields = ("game_key", "message", "user__email")
    readonly_fields = ("created_at", "updated_at")
