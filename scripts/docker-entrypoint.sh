#!/bin/sh
set -eu

if [ "${RAGRIG_AUTO_MIGRATE:-0}" = "1" ]; then
  uv run --no-dev alembic upgrade head
fi

exec "$@"
