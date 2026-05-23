from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "name", "avatar_url")
        read_only_fields = fields


class EmailAuthSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    # Optional: supplied on first sign-up so we can store a display name.
    name = serializers.CharField(required=False, allow_blank=True, max_length=120)

    def validate_password(self, value):
        # Defer full strength validation to the view (only on new accounts),
        # but reject obviously empty values early.
        if len(value) < 1:
            raise serializers.ValidationError("Password is required.")
        return value


class ProviderAuthSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=["apple", "google"])
    id_token = serializers.CharField()


class RefreshSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()


class SignOutSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()


def run_password_validators(password, user=None):
    validate_password(password, user=user)
