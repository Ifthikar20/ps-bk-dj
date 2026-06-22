from django.contrib import admin

from .models import GameSession


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
