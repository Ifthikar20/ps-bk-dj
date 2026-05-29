from django.urls import path

from .views import (
    ChildAnalyticsView,
    CompleteSectionView,
    HeartbeatView,
    LinkCodeView,
    MyProgressView,
    RedeemCodeView,
    StatusView,
    UnlinkView,
)

urlpatterns = [
    # Progress (student records own time + completion)
    path("progress/heartbeat/", HeartbeatView.as_view(), name="progress-heartbeat"),
    path("progress/complete/", CompleteSectionView.as_view(), name="progress-complete"),
    path("progress/me/", MyProgressView.as_view(), name="progress-me"),
    # Guardian linking + parent analytics
    path("guardian/code/", LinkCodeView.as_view(), name="guardian-code"),
    path("guardian/redeem/", RedeemCodeView.as_view(), name="guardian-redeem"),
    path("guardian/status/", StatusView.as_view(), name="guardian-status"),
    path(
        "guardian/children/<uuid:student_id>/",
        ChildAnalyticsView.as_view(),
        name="guardian-child",
    ),
    path("guardian/links/<int:link_id>/", UnlinkView.as_view(), name="guardian-unlink"),
]
