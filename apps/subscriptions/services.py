from django.conf import settings
from django.utils import timezone

from apps.common.exceptions import FreeLimitReached

from .models import Subscription


def is_premium_active(sub: Subscription) -> bool:
    if not sub.is_premium:
        return False
    if sub.expires_at is not None and sub.expires_at < timezone.now():
        return False
    return True


def remaining_free(sub: Subscription) -> int:
    return max(0, settings.FREE_GENERATION_LIMIT - sub.usage_count)


def can_generate(sub: Subscription) -> bool:
    return is_premium_active(sub) or remaining_free(sub) > 0


def assert_can_generate(user) -> None:
    """Raise 402 free_limit_reached if the user is out of free generations."""
    sub, _ = Subscription.objects.get_or_create(user=user)
    if not can_generate(sub):
        raise FreeLimitReached()
