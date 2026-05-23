from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"status": "ok"})


api_v1 = [
    path("", include("apps.accounts.urls")),
    path("", include("apps.studysets.urls")),
    path("", include("apps.generation.urls")),
    path("", include("apps.rewards.urls")),
    path("", include("apps.subscriptions.urls")),
    path("", include("apps.examprep.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/v1/", include((api_v1, "api"), namespace="v1")),
]
