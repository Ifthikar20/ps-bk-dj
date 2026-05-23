from django.contrib import admin

from .models import Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "is_premium", "usage_count", "platform", "expires_at")
    list_filter = ("is_premium", "platform")
    search_fields = ("user__email", "original_txn_id")
