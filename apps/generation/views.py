import uuid

from django.conf import settings
from django.core.files.storage import default_storage
from django.db.models import Count, Sum
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import DomainError

from .models import TokenUsage


class TokenUsageView(APIView):
    """Per-user token consumption: totals plus a per-model breakdown."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = TokenUsage.objects.filter(user=request.user)
        totals = qs.aggregate(
            input=Sum("input_tokens"),
            output=Sum("output_tokens"),
            total=Sum("total_tokens"),
            calls=Count("id"),
        )
        by_model = list(
            qs.values("provider", "model")
            .annotate(total=Sum("total_tokens"), calls=Count("id"))
            .order_by("-total")
        )
        return Response(
            {
                "totalInputTokens": totals["input"] or 0,
                "totalOutputTokens": totals["output"] or 0,
                "totalTokens": totals["total"] or 0,
                "calls": totals["calls"] or 0,
                "byModel": by_model,
            }
        )


class UploadView(APIView):
    """Store an uploaded file privately and return its storage key.

    The client then sends that key as `sourceRef` with `sourceKind: "file"`.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        file_obj = request.FILES.get("file")
        if file_obj is None:
            raise DomainError("No file was provided.", code="no_file")

        if file_obj.size > settings.MAX_UPLOAD_BYTES:
            raise DomainError(
                "File exceeds the maximum allowed size.",
                code="file_too_large",
                status_code=413,
            )

        ext = file_obj.name.rsplit(".", 1)[-1].lower() if "." in file_obj.name else ""
        if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
            raise DomainError(
                f"Unsupported file type: .{ext}",
                code="unsupported_file_type",
                status_code=415,
            )

        # Namespaced per-user, randomized key — no client-controlled paths.
        key = f"uploads/{request.user.id}/{uuid.uuid4().hex}.{ext}"
        saved_key = default_storage.save(key, file_obj)

        return Response({"key": saved_key}, status=status.HTTP_201_CREATED)
