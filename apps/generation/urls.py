from django.urls import path

from .views import TokenUsageView, UploadView

urlpatterns = [
    path("uploads/", UploadView.as_view(), name="upload"),
    path("me/tokens/", TokenUsageView.as_view(), name="token-usage"),
]
