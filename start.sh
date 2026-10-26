#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

PY=python3
if ! command -v "$PY" >/dev/null 2>&1; then
  PY=python
fi
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "[Edu] Python 3.10+ was not found. Install it and try again."
  exit 1
fi

if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "[Edu] Python 3.10 or newer is required."
  "$PY" --version
  exit 1
fi

if [ -x ".venv/bin/python" ] && ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
  echo "[Edu] Existing virtual environment is broken, recreating..."
  rm -rf .venv
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "[Edu] Creating virtual environment..."
  "$PY" -m venv .venv
fi

if [ -f ".venv/.deps-ok" ] && ! .venv/bin/python -c "import fastapi, uvicorn, httpx, pptx" >/dev/null 2>&1; then
  rm -f .venv/.deps-ok
fi

if [ ! -f ".venv/.deps-ok" ]; then
  echo "[Edu] Installing Python dependencies (first run only)..."
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
  touch .venv/.deps-ok
fi

if [ ! -f "web/dist/index.html" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "[Edu] Frontend is missing and npm was not found. Install Node.js 18+."
    exit 1
  fi
  echo "[Edu] Building the frontend (first run only)..."
  (cd web && npm install --no-audit --no-fund && npm run build)
fi

echo
echo "[Edu] Starting server. Press Ctrl+C to stop."
echo
exec .venv/bin/python -m server.main "$@"
