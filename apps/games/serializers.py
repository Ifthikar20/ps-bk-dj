from rest_framework import serializers

from .models import Game, GameSession, GameTelemetry


class GameSerializer(serializers.ModelSerializer):
    """Manifest shape consumed by the Flutter RemoteWebGame. Field names go out
    camelCase via the global renderer, so e.g. cover_colors -> coverColors."""

    class Meta:
        model = Game
        fields = (
            "key",
            "slug",
            "version",
            "name",
            "description",
            "icon",
            "emoji",
            "cover_colors",
            "difficulty",
            "requires",
            "min_app_version",
            "sdk_version",
        )


class GameTelemetrySerializer(serializers.Serializer):
    """Input for POST /games/telemetry."""

    game_key = serializers.SlugField(max_length=64)
    version = serializers.SlugField(max_length=32, required=False, allow_blank=True)
    kind = serializers.ChoiceField(choices=GameTelemetry.Kind.values)
    message = serializers.CharField(max_length=500, required=False, allow_blank=True)
    context = serializers.JSONField(required=False)


# Cap the save-state blob so a client can't stuff the DB via the progress field.
MAX_PROGRESS_BYTES = 32 * 1024


def _validate_progress_size(value):
    import json

    if value and len(json.dumps(value)) > MAX_PROGRESS_BYTES:
        raise serializers.ValidationError(
            f"progress exceeds {MAX_PROGRESS_BYTES} bytes."
        )
    return value


class GameSessionSerializer(serializers.ModelSerializer):
    """Read shape for a play record / play history."""

    class Meta:
        model = GameSession
        fields = (
            "id",
            "game_key",
            "study_set_id",
            "status",
            "score",
            "progress",
            "created_at",
            "completed_at",
        )
        read_only_fields = fields


class GameSessionStartSerializer(serializers.Serializer):
    """Input for starting a play: POST /games/sessions/."""

    game_key = serializers.SlugField(max_length=64)
    study_set_id = serializers.UUIDField(required=False, allow_null=True)
    progress = serializers.JSONField(
        required=False, validators=[_validate_progress_size]
    )


class GameSessionUpdateSerializer(serializers.Serializer):
    """Input for a heartbeat (PATCH) or completion: score / save-state."""

    score = serializers.IntegerField(required=False, min_value=0)
    progress = serializers.JSONField(
        required=False, validators=[_validate_progress_size]
    )
