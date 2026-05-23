"""Store receipt validation.

Stubs for Apple App Store Server API and Google Play Developer API. In
production these verify the receipt with the store, returning the entitlement
window. They are isolated here so the view stays thin and the integrations are
swappable/testable.
"""
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from apps.common.exceptions import DomainError


@dataclass
class Entitlement:
    is_premium: bool
    expires_at: object
    original_txn_id: str


class ReceiptError(DomainError):
    status_code = 422
    default_code = "invalid_receipt"
    default_detail = "Could not validate the purchase receipt."


def validate_apple(receipt: str) -> Entitlement:
    # TODO: call Apple App Store Server API (verifyReceipt / Server API JWS).
    raise ReceiptError("Apple receipt validation is not yet configured.")


def validate_google(receipt: str) -> Entitlement:
    # TODO: call Google Play Developer API purchases.subscriptions.get.
    raise ReceiptError("Google receipt validation is not yet configured.")


def validate_receipt(platform: str, receipt: str) -> Entitlement:
    if platform == "apple":
        return validate_apple(receipt)
    if platform == "google":
        return validate_google(receipt)
    raise ReceiptError("Unsupported platform.")
