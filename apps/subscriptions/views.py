from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Subscription
from .receipts import validate_receipt
from .serializers import SubscriptionSerializer, ValidateReceiptSerializer


def _sub(user):
    return Subscription.objects.get_or_create(user=user)[0]


class SubscriptionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(SubscriptionSerializer(_sub(request.user)).data)


class ValidateReceiptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ValidateReceiptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entitlement = validate_receipt(
            serializer.validated_data["platform"],
            serializer.validated_data["receipt"],
        )
        sub = _sub(request.user)
        sub.is_premium = entitlement.is_premium
        sub.expires_at = entitlement.expires_at
        sub.platform = serializer.validated_data["platform"]
        sub.original_txn_id = entitlement.original_txn_id
        sub.save()
        return Response(SubscriptionSerializer(sub).data)


class CancelView(APIView):
    """Dev/testing only — production relies on store-to-server webhooks."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not settings.DEBUG:
            from apps.common.exceptions import DomainError

            raise DomainError(
                "Cancellation is handled by the store.",
                code="not_allowed",
                status_code=403,
            )
        sub = _sub(request.user)
        sub.is_premium = False
        sub.expires_at = None
        sub.save(update_fields=["is_premium", "expires_at"])
        return Response(SubscriptionSerializer(sub).data)
