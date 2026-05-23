"""Consistent error envelope so the Flutter client can render LearningError / toasts.

    {"error": {"code": "...", "message": "...", "details": {}}}
"""
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler


class DomainError(APIException):
    """Base for domain errors that carry a stable machine-readable code."""

    status_code = 400
    default_code = "bad_request"
    default_detail = "Request could not be processed."

    def __init__(self, message=None, code=None, status_code=None, details=None):
        self.code = code or self.default_code
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code
        super().__init__(message or self.default_detail)


class FreeLimitReached(DomainError):
    status_code = 402
    default_code = "free_limit_reached"
    default_detail = "You've used all your free generations."


class GenerationError(DomainError):
    status_code = 422
    default_code = "generation_failed"
    default_detail = "Could not generate a study set from that source."


def _code_for(exc, response):
    if isinstance(exc, DomainError):
        return exc.code
    mapping = {
        400: "bad_request",
        401: "unauthenticated",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        429: "rate_limited",
    }
    return mapping.get(response.status_code, "error")


def api_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    message = None
    details = {}

    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        message = str(detail["detail"])
    elif isinstance(detail, dict):
        details = detail
        message = "Validation failed."
    elif isinstance(detail, list):
        details = {"errors": detail}
        message = "Validation failed."
    else:
        message = str(detail)

    if isinstance(exc, DomainError):
        message = str(exc.detail)
        details = exc.details or details

    response.data = {
        "error": {
            "code": _code_for(exc, response),
            "message": message,
            "details": details,
        }
    }
    return response
