import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

from decouple import Csv

from .base import *  # noqa: F401,F403
from .base import config

DEBUG = False

# Origins allowed to submit POST/PUT/etc. forms — needed for Django admin login.
# Include scheme: e.g. "http://100.55.196.80" or "https://api.playstudy.ai".
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

# --- Hardened transport / cookies ---
# Defaults match a TLS deployment. Override via env when running on raw HTTP
# (e.g. an EC2 IP with no domain/cert yet) by setting SECURE_SSL_REDIRECT=False
# and the cookie flags to False in .env.prod.
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=31536000, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True, cast=bool)
SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=True, cast=bool)
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=True, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=True, cast=bool)
X_FRAME_OPTIONS = "DENY"

# --- Observability --- #
SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=config("SENTRY_TRACES_RATE", default=0.1, cast=float),
        send_default_pii=False,
        environment=config("ENVIRONMENT", default="production"),
    )
