"""Server-authoritative rewards engine.

The client sends a *reason* (+ context); the server decides the points. This
mirrors the economy in RewardsBloc exactly so behaviour is unchanged, but the
math can no longer be forged.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction

from apps.common.exceptions import DomainError

from .models import PointEvent, RewardProfile


def _points_for(reason: str, context: dict) -> int:
    context = context or {}
    if reason == "Created a study set":
        return 20
    if reason == "Finished a quiz":
        return 5 + int(context.get("score", 0)) * 5
    if reason == "Guessed a word":
        return max(0, 15 - int(context.get("mistakes", 0)) * 2)
    if reason == "Super Dash checkpoint":
        return 5
    if reason == "Daily exam session":
        return 10 + int(context.get("correct", 0)) * 5
    raise DomainError(f"Unknown reward reason: {reason}", code="unknown_reason")


def _user_today(user) -> str:
    tz = ZoneInfo(getattr(user, "timezone", "UTC") or "UTC")
    return datetime.now(tz).strftime("%Y-%m-%d")


def _ymd_offset(ymd_today: str, days: int) -> str:
    d = datetime.strptime(ymd_today, "%Y-%m-%d") + timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def effective_streak(profile: RewardProfile, today: str) -> int:
    """A streak is broken if the last activity was before yesterday."""
    last = profile.last_active_ymd
    if last is None:
        return 0
    yesterday = _ymd_offset(today, -1)
    if last != today and last != yesterday:
        return 0
    return profile.streak


@transaction.atomic
def award(user, reason: str, context: dict | None = None) -> dict:
    points = _points_for(reason, context or {})
    today = _user_today(user)

    profile = (
        RewardProfile.objects.select_for_update()
        .get_or_create(user=user)[0]
    )
    profile.refresh_from_db()

    last = profile.last_active_ymd
    yesterday = _ymd_offset(today, -1)
    if last == today:
        pass  # streak already counted today
    elif last == yesterday:
        profile.streak += 1
    else:
        profile.streak = 1

    profile.points += points
    profile.last_active_ymd = today
    profile.save(update_fields=["points", "streak", "last_active_ymd"])

    PointEvent.objects.create(user=user, points=points, reason=reason)

    return {"profile": profile, "last_award": points, "last_reason": reason}


def get_rewards_state(user) -> RewardProfile:
    return RewardProfile.objects.get_or_create(user=user)[0]
