from django.urls import path

from .views import ActivityView, RewardsView

urlpatterns = [
    path("rewards/", RewardsView.as_view(), name="rewards"),
    path("rewards/activity/", ActivityView.as_view(), name="rewards-activity"),
]
