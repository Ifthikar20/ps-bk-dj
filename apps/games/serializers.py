from rest_framework import serializers

from .models import Game


class GameSerializer(serializers.ModelSerializer):
    """Manifest shape consumed by the Flutter RemoteWebGame.

    Field names go out camelCase via the global CamelCase renderer, so e.g.
    ``cover_colors`` -> ``coverColors`` to match the Dart side.
    """

    class Meta:
        model = Game
        fields = (
            "key",
            "slug",
            "name",
            "description",
            "icon",
            "emoji",
            "cover_colors",
            "difficulty",
            "requires",
            "min_app_version",
        )
