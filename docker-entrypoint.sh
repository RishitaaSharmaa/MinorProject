#!/bin/sh
set -e
alembic upgrade head
if [ "$DEMO_MODE" = "true" ]; then
  python -m scripts.demo_bootstrap
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
