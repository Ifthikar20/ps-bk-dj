from django.contrib import admin

from .models import Game, GameSession


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "slug", "difficulty", "enabled", "sort_order")
    list_filter = ("enabled", "difficulty")
    list_editable = ("enabled", "sort_order")
    search_fields = ("name", "key", "slug")
    readonly_fields = ("id", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("name", "key", "slug", "description")}),
        ("Presentation", {"fields": ("icon", "emoji", "cover_colors", "difficulty")}),
        ("Gating", {"fields": ("requires", "min_app_version", "enabled", "sort_order")}),
        ("Meta", {"fields": ("id", "created_at", "updated_at")}),
    )


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = (
        "game_key",
        "user",
        "status",
        "score",
        "reward_points",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "game_key")
    search_fields = ("game_key", "user__email")
    readonly_fields = ("id", "created_at", "updated_at", "completed_at")
