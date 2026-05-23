from django.urls import path

from .views import CancelView, SubscriptionView, ValidateReceiptView

urlpatterns = [
    path("subscription/", SubscriptionView.as_view(), name="subscription"),
    path("subscription/validate/", ValidateReceiptView.as_view(), name="subscription-validate"),
    path("subscription/cancel/", CancelView.as_view(), name="subscription-cancel"),
]
