"""Base settings shared across all environments.

Environment-specific overrides live in ``dev.py`` and ``prod.py``. Secrets and
deploy-time knobs are read from the environment via ``python-decouple`` so the
same image runs everywhere and nothing sensitive is committed.
"""
from datetime import timedelta
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #
SECRET_KEY = config("SECRET_KEY", default="dev-insecure-change-me")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

AUTH_USER_MODEL = "accounts.User"
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "corsheaders",
    "django_celery_results",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.studysets",
    "apps.generation",
    "apps.rewards",
    "apps.subscriptions",
    "apps.examprep",
    "apps.family",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.gzip.GZipMiddleware",  # compress JSON responses
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------- #
# Database (PostgreSQL)
# --------------------------------------------------------------------------- #
import dj_database_url  # noqa: E402

DATABASES = {
    "default": dj_database_url.config(
        default=config(
            "DATABASE_URL",
            default="postgres://playstudy:playstudy@localhost:5432/playstudy",
        ),
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# SQLite serializes writes via a file lock; with the background generation
# thread + heartbeats every 15s + rewards writes it is easy to hit
# "database is locked". WAL lets readers and writers proceed concurrently
# and `timeout` makes writers wait up to 30s for the lock instead of erroring.
if DATABASES["default"].get("ENGINE", "").endswith("sqlite3"):
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"]["timeout"] = 30
    DATABASES["default"]["OPTIONS"]["init_command"] = (
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"
    )

# --------------------------------------------------------------------------- #
# Cache / Celery / Redis
# --------------------------------------------------------------------------- #
REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

CELERY_BROKER_URL = config("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = "django-db"
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 120
CELERY_TASK_SOFT_TIME_LIMIT = 110
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

# --------------------------------------------------------------------------- #
# Password validation / hashing (PBKDF2 by default — strong + portable)
# --------------------------------------------------------------------------- #
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------- #
# DRF
# --------------------------------------------------------------------------- #
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    # camelCase wire format to match the Flutter Dart models exactly.
    "DEFAULT_RENDERER_CLASSES": (
        "djangorestframework_camel_case.render.CamelCaseJSONRenderer",
    ),
    "DEFAULT_PARSER_CLASSES": (
        "djangorestframework_camel_case.parser.CamelCaseJSONParser",
        "djangorestframework_camel_case.parser.CamelCaseMultiPartParser",
        "djangorestframework_camel_case.parser.CamelCaseFormParser",
    ),
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "user": "1000/day",
        "anon": "60/hour",
        "auth": "10/min",         # brute-force protection on login
        "generation": "10/hour",   # expensive AI generation
        "rewards": "120/hour",     # bound client-reported point farming
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": config("JWT_SIGNING_KEY", default=SECRET_KEY),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# --------------------------------------------------------------------------- #
# CORS (the mobile app uses native networking; web/debug clients need this)
# --------------------------------------------------------------------------- #
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="", cast=Csv())
CORS_ALLOW_CREDENTIALS = True

# --------------------------------------------------------------------------- #
# Storage (S3 for uploads, local fallback in dev)
# --------------------------------------------------------------------------- #
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME", default="")
AWS_S3_REGION_NAME = config("AWS_S3_REGION_NAME", default="")
AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY", default="")
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True  # signed URLs — uploads are private by default

if AWS_STORAGE_BUCKET_NAME:
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }

# --------------------------------------------------------------------------- #
# Domain config
# --------------------------------------------------------------------------- #
# --- LLM provider (pluggable) ---
# AI keys live only here, never in the app.
# Options: "deepseek" | "local" | "gemini"
LLM_PROVIDER = config("LLM_PROVIDER", default="anthropic")
# deepseek-chat is a low-cost model; cap output tokens to keep Q&A generation cheap.
LLM_MAX_OUTPUT_TOKENS = config("LLM_MAX_OUTPUT_TOKENS", default=8192, cast=int)
LLM_TEMPERATURE = config("LLM_TEMPERATURE", default=0.4, cast=float)

# DeepSeek (OpenAI-compatible API).
DEEPSEEK_API_KEY = config("DEEPSEEK_API_KEY", default="")
DEEPSEEK_BASE_URL = config("DEEPSEEK_BASE_URL", default="https://api.deepseek.com")
DEEPSEEK_MODEL = config("DEEPSEEK_MODEL", default="deepseek-chat")

# Local model (OpenAI-compatible: Ollama / vLLM / LM Studio).
LOCAL_LLM_BASE_URL = config("LOCAL_LLM_BASE_URL", default="http://localhost:11434/v1")
LOCAL_LLM_API_KEY = config("LOCAL_LLM_API_KEY", default="not-needed")
LOCAL_LLM_MODEL = config("LOCAL_LLM_MODEL", default="llama3.1")

# Gemini.
GEMINI_API_KEY = config("GEMINI_API_KEY", default="")
GEMINI_MODEL = config("GEMINI_MODEL", default="gemini-1.5-flash")

# Anthropic (Claude). Haiku is the cheapest/fastest for quiz generation.
ANTHROPIC_API_KEY = config("ANTHROPIC_API_KEY", default="")
ANTHROPIC_MODEL = config("ANTHROPIC_MODEL", default="claude-haiku-4-5")

# Free-tier generation limit — MUST equal SubscriptionBloc.freeLimit in the app.
FREE_GENERATION_LIMIT = config("FREE_GENERATION_LIMIT", default=2, cast=int)

# Upload guards
MAX_UPLOAD_BYTES = config("MAX_UPLOAD_BYTES", default=20 * 1024 * 1024, cast=int)
ALLOWED_UPLOAD_EXTENSIONS = [
    "pdf", "txt", "md", "doc", "docx", "png", "jpg", "jpeg",
]

# Social auth
GOOGLE_OAUTH_CLIENT_IDS = config("GOOGLE_OAUTH_CLIENT_IDS", default="", cast=Csv())
APPLE_BUNDLE_IDS = config("APPLE_BUNDLE_IDS", default="", cast=Csv())

# --------------------------------------------------------------------------- #
# Request hardening (applies in every environment)
# --------------------------------------------------------------------------- #
# Cap request body size to blunt memory-exhaustion / oversized-payload abuse.
DATA_UPLOAD_MAX_MEMORY_SIZE = config(
    "DATA_UPLOAD_MAX_MEMORY_SIZE", default=5 * 1024 * 1024, cast=int
)
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------- #
# Logging (structured, JSON-friendly)
# --------------------------------------------------------------------------- #
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": config("LOG_LEVEL", default="INFO")},
}
