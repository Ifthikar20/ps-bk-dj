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


# Reasons the client may self-report (in-app gameplay the server can't observe).
# Creation + exam-session rewards are awarded server-side on the real event, so
# they are NOT accepted from the client.
CLIENT_REPORTABLE_REASONS = {
    "Finished a quiz",
    "Guessed a word",
    "Super Dash checkpoint",
}

# Hard ceilings per reason so a tampered context can't mint huge point totals.
_MAX_POINTS = {
    "Created a study set": 20,
    "Finished a quiz": 55,        # score capped at 10
    "Guessed a word": 15,
    "Super Dash checkpoint": 5,
    "Daily exam session": 60,     # correct capped at 10
}


def _int(value, lo=0, hi=10_000) -> int:
    """Coerce untrusted context numbers into a sane bounded int."""
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return 0


def _points_for(reason: str, context: dict) -> int:
    context = context or {}
    if reason == "Created a study set":
        points = 20
    elif reason == "Finished a quiz":
        points = 5 + _int(context.get("score")) * 5
    elif reason == "Guessed a word":
        points = max(0, 15 - _int(context.get("mistakes")) * 2)
    elif reason == "Super Dash checkpoint":
        points = 5
    elif reason == "Daily exam session":
        points = 10 + _int(context.get("correct")) * 5
    else:
        raise DomainError(f"Unknown reward reason: {reason}", code="unknown_reason")
    return min(points, _MAX_POINTS.get(reason, points))


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
def award(user, reason: str, context: dict | None = None, dedupe_key: str | None = None) -> dict:
    points = _points_for(reason, context or {})
    today = _user_today(user)

    profile = (
        RewardProfile.objects.select_for_update()
        .get_or_create(user=user)[0]
    )
    profile.refresh_from_db()

    # Idempotency: a real-world event keyed by dedupe_key is only ever awarded
    # once, even on retries / concurrent requests.
    if dedupe_key and PointEvent.objects.filter(
        user=user, dedupe_key=dedupe_key
    ).exists():
        return {"profile": profile, "last_award": 0, "last_reason": reason}

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

    PointEvent.objects.create(
        user=user, points=points, reason=reason, dedupe_key=dedupe_key
    )

    return {"profile": profile, "last_award": points, "last_reason": reason}


def get_rewards_state(user) -> RewardProfile:
    return RewardProfile.objects.get_or_create(user=user)[0]


def points_history(user, days: int = 14) -> list[dict]:
    """Per-day points + activity count for the last `days` days, in the user's
    timezone. Drives the activity chart / streak heatmap.
    """
    days = max(7, min(90, int(days)))
    tz = ZoneInfo(getattr(user, "timezone", "UTC") or "UTC")
    today = datetime.now(tz).date()
    start = today - timedelta(days=days - 1)

    buckets = {
        (start + timedelta(days=i)).isoformat(): {"points": 0, "count": 0}
        for i in range(days)
    }

    start_utc = datetime(start.year, start.month, start.day, tzinfo=tz)
    events = PointEvent.objects.filter(user=user, created_at__gte=start_utc).only(
        "points", "created_at"
    )
    for event in events:
        ymd = event.created_at.astimezone(tz).date().isoformat()
        if ymd in buckets:
            buckets[ymd]["points"] += event.points
            buckets[ymd]["count"] += 1

    return [
        {"ymd": ymd, "points": b["points"], "count": b["count"]}
        for ymd, b in sorted(buckets.items())
    ]
