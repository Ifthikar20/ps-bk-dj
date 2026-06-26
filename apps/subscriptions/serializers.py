from django.conf import settings
from rest_framework import serializers

from .models import Subscription
from .services import (
    can_generate,
    effective_usage,
    is_premium_active,
    remaining_free,
    usage_resets_at,
)


class SubscriptionSerializer(serializers.ModelSerializer):
    is_premium = serializers.SerializerMethodField()
    # usage_count reflects the CURRENT monthly window (0 after a rollover), not
    # the raw lifetime column, so the profile screen shows "this month".
    usage_count = serializers.SerializerMethodField()
    usage_limit = serializers.SerializerMethodField()
    usage_resets_at = serializers.SerializerMethodField()
    remaining_free = serializers.SerializerMethodField()
    can_generate = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = (
            "is_premium",
            "usage_count",
            "usage_limit",
            "usage_resets_at",
            "remaining_free",
            "can_generate",
            "expires_at",
        )

    def get_is_premium(self, obj):
        return is_premium_active(obj)

    def get_usage_count(self, obj):
        return effective_usage(obj)

    def get_usage_limit(self, obj):
        return settings.FREE_GENERATION_LIMIT

    def get_usage_resets_at(self, obj):
        return usage_resets_at(obj).isoformat()

    def get_remaining_free(self, obj):
        return remaining_free(obj)

    def get_can_generate(self, obj):
        return can_generate(obj)


class ValidateReceiptSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=["apple", "google"])
    receipt = serializers.CharField()
