from .base import *  # noqa: F401,F403
from .base import config

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Run Celery work synchronously in dev so generation results appear without a worker.
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", default=True, cast=bool)
CELERY_TASK_EAGER_PROPAGATES = True

# Allow any localhost web origin while developing.
CORS_ALLOW_ALL_ORIGINS = True

# Dev doesn't need a shared rate-limit store; use in-process cache so the app
# runs without a local Redis. Production keeps Redis (see base.py).
if config("USE_LOCMEM_CACHE", default=True, cast=bool):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
