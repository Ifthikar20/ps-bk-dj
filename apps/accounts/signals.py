from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def bootstrap_user_profiles(sender, instance, created, **kwargs):
    """Every user gets a rewards profile and a subscription row on creation."""
    if not created:
        return
    from apps.rewards.models import RewardProfile
    from apps.subscriptions.models import Subscription

    RewardProfile.objects.get_or_create(user=instance)
    Subscription.objects.get_or_create(user=instance)
