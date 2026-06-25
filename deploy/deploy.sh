#!/usr/bin/env bash
# Pull, build, migrate, restart. Run on the EC2 box from the repo root.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env.prod ]]; then
  echo "ERROR: .env.prod missing. Copy .env.prod.example and fill it in." >&2
  exit 1
fi

echo "==> git pull"
git pull --ff-only

echo "==> build images"
docker compose --env-file .env.prod build web

echo "==> start postgres + redis (idempotent)"
docker compose --env-file .env.prod up -d postgres redis

echo "==> migrate"
docker compose --env-file .env.prod run --rm web python manage.py migrate --noinput

echo "==> collectstatic"
docker compose --env-file .env.prod run --rm web python manage.py collectstatic --noinput

echo "==> restart web + worker + caddy"
docker compose --env-file .env.prod up -d --no-deps web worker caddy

echo "==> done. Recent logs:"
docker compose --env-file .env.prod ps
echo
docker compose --env-file .env.prod logs --tail=20 web caddy
