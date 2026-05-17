#!/bin/sh
set -eu

if [ "${RAGRIG_AUTO_MIGRATE:-0}" = "1" ]; then
  uv run --no-dev alembic upgrade head
fi

# Idempotent demo seed — first-run convenience for `docker compose up`.
# Failure does not block startup; admins running without sample data can
# safely set RAGRIG_DEMO_SEED=0.
if [ "${RAGRIG_DEMO_SEED:-0}" = "1" ]; then
  uv run --no-dev python -m scripts.seed_demo || \
    echo "warning: demo seed failed; continuing without sample data"
fi

exec "$@"
