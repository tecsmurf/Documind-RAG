#!/bin/sh
# Container entrypoint: apply migrations (additive, never drops data), then serve.
set -e
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  alembic upgrade head
fi
# One worker by default: Render free tier has 512 MB, and the in-memory rate limiter
# is only correct per process (set REDIS_URL before raising WEB_CONCURRENCY).
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}" --no-server-header --timeout-graceful-shutdown 20
