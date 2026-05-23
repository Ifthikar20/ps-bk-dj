from django.contrib import admin

from .models import PointEvent, RewardProfile


@admin.register(RewardProfile)
class RewardProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "points", "streak", "last_active_ymd")
    search_fields = ("user__email",)


@admin.register(PointEvent)
class PointEventAdmin(admin.ModelAdmin):
    list_display = ("user", "points", "reason", "created_at")
    list_filter = ("reason",)
    search_fields = ("user__email",)
