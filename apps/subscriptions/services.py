import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import FreeLimitReached

from .models import Subscription


def is_premium_active(sub: Subscription) -> bool:
    if not sub.is_premium:
        return False
    if sub.expires_at is not None and sub.expires_at < timezone.now():
        return False
    return True


def _period_start(now=None) -> datetime.date:
    """First day of the current monthly usage window."""
    today = (now or timezone.now()).date()
    return today.replace(day=1)


def usage_resets_at(sub: Subscription, now=None) -> datetime.date:
    """First day of the NEXT monthly window — i.e. when usage_count rolls to 0."""
    start = _period_start(now)
    if start.month == 12:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)


def effective_usage(sub: Subscription, now=None) -> int:
    """Usage in the current window. Treats a stale period as already reset, so
    reads (serializers, limit checks) reflect the monthly rollover without
    having to write to the row — the actual reset write happens lazily on the
    next consume_free_credit()."""
    if sub.usage_period_start != _period_start(now):
        return 0
    return sub.usage_count


def remaining_free(sub: Subscription) -> int:
    return max(0, settings.FREE_GENERATION_LIMIT - effective_usage(sub))


def can_generate(sub: Subscription) -> bool:
    return is_premium_active(sub) or remaining_free(sub) > 0


def assert_can_generate(user) -> None:
    """Raise 402 free_limit_reached if the user is out of free generations."""
    sub, _ = Subscription.objects.get_or_create(user=user)
    if not can_generate(sub):
        raise FreeLimitReached()


def consume_free_credit(user) -> None:
    """Record one free-tier generation against the current monthly window.

    Premium users are exempt. Rolls the counter over to a fresh window first
    when the stored period is stale, so free credits are per-month rather than
    lifetime. Row-locked to stay correct under concurrent generations.
    """
    with transaction.atomic():
        try:
            sub = Subscription.objects.select_for_update().get(user=user)
        except Subscription.DoesNotExist:
            return
        if is_premium_active(sub):
            return
        start = _period_start()
        if sub.usage_period_start != start:
            sub.usage_count = 0
            sub.usage_period_start = start
        sub.usage_count += 1
        sub.save(update_fields=["usage_count", "usage_period_start"])
