from django.urls import path

from .views import ActivityView, RewardsHistoryView, RewardsView

urlpatterns = [
    path("rewards/", RewardsView.as_view(), name="rewards"),
    path("rewards/history/", RewardsHistoryView.as_view(), name="rewards-history"),
    path("rewards/activity/", ActivityView.as_view(), name="rewards-activity"),
]
