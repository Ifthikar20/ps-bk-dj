from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path, re_path
from django.views.static import serve as static_serve


def health(_request):
    return JsonResponse({"status": "ok"})


api_v1 = [
    path("", include("apps.accounts.urls")),
    path("", include("apps.studysets.urls")),
    path("", include("apps.generation.urls")),
    path("", include("apps.rewards.urls")),
    path("", include("apps.subscriptions.urls")),
    path("", include("apps.examprep.urls")),
    path("", include("apps.family.urls")),
    path("", include("apps.games.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/v1/", include((api_v1, "api"), namespace="v1")),
]

# Dev only: serve the static HTML game bundles (games_host/) so the web app can
# load them in an iframe. In production these are served from a CDN
# (GAMES_BASE_URL). Bundles live at games_host/games/<slug>/<version>/ and load
# the SDK from the host root (../../../playstudy-sdk.js), so we serve at root.
if settings.DEBUG:
    _games_root = str(settings.BASE_DIR / "games_host")
    urlpatterns += [
        re_path(
            r"^(?P<path>(?:games/.*|playstudy-sdk\.js|sw\.js))$",
            static_serve,
            {"document_root": _games_root},
        ),
    ]
