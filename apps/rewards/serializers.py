from rest_framework import serializers

from .ranks import rank_for, rank_progress
from .services import _user_today, effective_streak


class RankSerializer(serializers.Serializer):
    name = serializers.CharField()
    emoji = serializers.CharField()
    threshold = serializers.IntegerField()


class RewardProfileSerializer(serializers.Serializer):
    """Renders the rewards payload the adventure_page needs."""

    points = serializers.IntegerField()
    streak = serializers.SerializerMethodField()
    rank = serializers.SerializerMethodField()
    next_rank = serializers.SerializerMethodField()
    rank_progress = serializers.SerializerMethodField()
    points_to_next_rank = serializers.SerializerMethodField()
    last_award = serializers.SerializerMethodField()
    last_reason = serializers.SerializerMethodField()

    def get_streak(self, obj):
        return effective_streak(obj, _user_today(obj.user))

    def get_rank(self, obj):
        current, _ = rank_for(obj.points)
        return RankSerializer(current).data

    def get_next_rank(self, obj):
        _, nxt = rank_for(obj.points)
        return RankSerializer(nxt).data if nxt else None

    def get_rank_progress(self, obj):
        return rank_progress(obj.points)[0]

    def get_points_to_next_rank(self, obj):
        return rank_progress(obj.points)[1]

    def _last_event(self, obj):
        if not hasattr(self, "_cached_event"):
            self._cached_event = obj.user.point_events.first()
        return self._cached_event

    def get_last_award(self, obj):
        event = self._last_event(obj)
        return event.points if event else 0

    def get_last_reason(self, obj):
        event = self._last_event(obj)
        return event.reason if event else None
