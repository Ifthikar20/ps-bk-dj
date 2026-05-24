#!/usr/bin/env bash
# One-shot setup/bootstrap for the PlayStudy backend.
#
#   ./setup.sh          # set up everything, then start the dev server
#   ./setup.sh --no-run # set up everything, but don't start the server
#
# Safe to re-run: it skips work that's already done. Set PYTHON=/path/to/python
# to force a specific interpreter.
set -euo pipefail
cd "$(dirname "$0")"

RUN_SERVER=1
[[ "${1:-}" == "--no-run" ]] && RUN_SERVER=0

# The deps (pydantic, Django 5.1, Pillow, ...) only have wheels for / support
# CPython 3.9–3.13. 3.14 has no wheels yet and falls back to a Rust build that
# fails, so we explicitly require a supported interpreter.
is_supported() { "$1" -c 'import sys; sys.exit(0 if (3,9)<=sys.version_info[:2]<(3,14) else 1)' >/dev/null 2>&1; }

pick_python() {
  if [[ -n "${PYTHON:-}" ]]; then
    is_supported "$PYTHON" && { echo "$PYTHON"; return 0; }
    echo "    requested PYTHON=$PYTHON is not in the 3.9–3.13 range" >&2
  fi
  local c
  for c in python3.13 python3.12 python3.11 python3.10 python3.9 python3 python; do
    if command -v "$c" >/dev/null 2>&1 && is_supported "$c"; then echo "$c"; return 0; fi
  done
  return 1
}

echo "==> 1/5 Virtual environment"
PY="$(pick_python || true)"
if [[ -z "$PY" ]]; then
  cat >&2 <<'MSG'
    ERROR: no supported Python found (need 3.9–3.13; 3.14 is too new for the deps).
    Install one and re-run, e.g.:
        brew install python@3.12
        PYTHON=python3.12 ./setup.sh
MSG
  exit 1
fi
echo "    using $(command -v "$PY") ($("$PY" -V 2>&1))"

# Rebuild the venv if it's missing or was built with an unsupported Python.
if [[ -d .venv ]] && ! is_supported .venv/bin/python; then
  echo "    existing .venv uses an unsupported Python — recreating"
  rm -rf .venv
fi
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
