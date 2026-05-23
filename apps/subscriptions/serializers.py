from rest_framework import serializers

from .models import Subscription
from .services import can_generate, is_premium_active, remaining_free


class SubscriptionSerializer(serializers.ModelSerializer):
    is_premium = serializers.SerializerMethodField()
    remaining_free = serializers.SerializerMethodField()
    can_generate = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = (
            "is_premium",
            "usage_count",
            "remaining_free",
            "can_generate",
            "expires_at",
        )

    def get_is_premium(self, obj):
        return is_premium_active(obj)

    def get_remaining_free(self, obj):
        return remaining_free(obj)

    def get_can_generate(self, obj):
        return can_generate(obj)


class ValidateReceiptSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=["apple", "google"])
    receipt = serializers.CharField()
