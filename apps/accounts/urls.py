from django.urls import path

from .views import (
    EmailAuthView,
    MeView,
    ProviderAuthView,
    RefreshView,
    SignOutView,
)

urlpatterns = [
    path("auth/email/", EmailAuthView.as_view(), name="auth-email"),
    path("auth/provider/", ProviderAuthView.as_view(), name="auth-provider"),
    path("auth/refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("auth/signout/", SignOutView.as_view(), name="auth-signout"),
    path("me/", MeView.as_view(), name="me"),
]
