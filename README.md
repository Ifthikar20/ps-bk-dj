# PlayStudy Backend (Django)

Server-authoritative backend for the PlayStudy Flutter app. Replaces the app's
local mocks with real, server-owned data. JSON is camelCase end-to-end to match
the Dart models, so the client's `fromJson`/`toJson` is reusable as-is.

## Stack

Django 5 · DRF · SimpleJWT · PostgreSQL · Redis · Celery · Gemini · S3.

## Layout

```
config/            settings (base/dev/prod), urls, celery, wsgi/asgi
apps/accounts/     custom User (UUID, email login), JWT, Apple/Google sign-in, /me bootstrap
apps/studysets/    StudySet (= LearningMaterial) + quiz + word game, async create
apps/generation/   ingestion (link/file/text) -> Gemini -> validated result, Celery task, uploads
apps/rewards/      server-authoritative points, streak, ranks (audit log so points can't be forged)
apps/subscriptions/ free-tier gate, usage count, IAP receipt validation
apps/examprep/     study plans + daily session results
apps/common/       UUID/timestamp base models, pagination, error envelope, permissions, throttles
```

## API (all under `/api/v1/`, Bearer auth except auth + health)

- `POST auth/email`, `auth/provider`, `auth/refresh`, `auth/signout`
- `GET  me` — auth + rewards + subscription bootstrap
- `GET/POST/DELETE studysets`, `GET studysets/{id}/status` — async generate (202 -> poll -> get)
- `POST uploads` — multipart, returns a storage key for `sourceKind:"file"`
- `GET rewards`, `POST rewards/activity` — server computes the points
- `GET subscription`, `POST subscription/validate`, `subscription/cancel`
- `examplans` CRUD + `POST examplans/{id}/sessions`

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in SECRET_KEY, GEMINI_API_KEY, DATABASE_URL...
python manage.py migrate
python manage.py runserver
# Generation runs inline in dev (CELERY_TASK_ALWAYS_EAGER=True).
# For the real async path: celery -A config worker -l info
```

Point the app at it: `flutter run --dart-define=API_BASE_URL=http://localhost:8000`.

## Security highlights

- JWT on all data endpoints; object-level isolation (`owner == request.user`).
- Generation gated server-side against the free limit — the client gate is never trusted.
- Free credit consumed only on a *successful* generation (in the Celery task).
- `Idempotency-Key` header on `POST /studysets/` prevents duplicate sets on retry.
- Throttles: generation 10/hour, auth 10/min (brute-force), per-user/anon defaults.
- Gemini key and IAP secrets live only in backend env, never in the app.
- Upload allow-listing (type + size), randomized per-user S3 keys, signed URLs.
- Prod: HSTS, secure cookies, SSL redirect, Sentry.
