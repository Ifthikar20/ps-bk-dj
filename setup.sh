#!/usr/bin/env bash
# One-shot setup/bootstrap for the PlayStudy backend.
#
#   ./setup.sh          # set up everything, then start the dev server
#   ./setup.sh --no-run # set up everything, but don't start the server
#
# Safe to re-run: it skips work that's already done.
set -euo pipefail
cd "$(dirname "$0")"

RUN_SERVER=1
[[ "${1:-}" == "--no-run" ]] && RUN_SERVER=0

PY="${PYTHON:-python3}"

echo "==> 1/5 Virtual environment"
if [[ ! -d .venv ]]; then
  "$PY" -m venv .venv
  echo "    created .venv"
else
  echo "    .venv already exists"
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> 2/5 Dependencies"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "    installed from requirements.txt"

echo "==> 3/5 Environment file"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "    created .env from .env.example — fill in SECRET_KEY, LLM keys, DATABASE_URL"
else
  echo "    .env already exists (left untouched)"
fi

echo "==> 4/5 Database migrations"
python manage.py migrate

echo "==> 5/5 Done"
if [[ "$RUN_SERVER" == "1" ]]; then
  echo "    starting dev server (Ctrl+C to stop)"
  exec python manage.py runserver
else
  echo "    skipping server (--no-run). Start it with: python manage.py runserver"
fi
