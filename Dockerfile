FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_PORT=8000 \
    RAGRIG_AUTO_MIGRATE=0

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.7.3 /uv /uvx /bin/

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts

RUN uv sync --no-dev --frozen

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD curl -fsS "http://127.0.0.1:${APP_PORT:-8000}/health" || exit 1

ENTRYPOINT ["sh", "/app/scripts/docker-entrypoint.sh"]

CMD ["sh", "-c", "uv run --no-dev uvicorn ragrig.main:app --host 0.0.0.0 --port ${APP_PORT:-8000}"]
