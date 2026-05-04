UV ?= uv

.PHONY: sync format lint test web-check test-db migrate migrate-down db-check db-shell run run-web up down logs ingest-local ingest-local-dry-run ingest-check index-local index-check retrieve-check

INGEST_KB ?= fixture-local
INGEST_ROOT ?= tests/fixtures/local_ingestion

sync:
	$(UV) sync --dev

format:
	$(UV) run ruff format .

lint:
	$(UV) run ruff check .

test:
	$(UV) run pytest

web-check:
	$(UV) run pytest tests/test_web_console.py

test-db:
	$(UV) run python -m scripts.db_check

migrate:
	$(UV) run alembic upgrade head

migrate-down:
	$(UV) run alembic downgrade -1

db-check:
	$(UV) run python -m scripts.db_check

db-shell:
	docker compose exec db psql -U ragrig -d ragrig

run:
	$(UV) run uvicorn ragrig.main:app --host 0.0.0.0 --port 8000 --reload

run-web:
	$(UV) run python -m scripts.run_web

up:
	docker compose up --build

down:
	docker compose down --remove-orphans

logs:
	docker compose logs -f

ingest-local:
	$(UV) run python -m scripts.ingest_local --knowledge-base "$(INGEST_KB)" --root-path "$(INGEST_ROOT)"

ingest-local-dry-run:
	$(UV) run python -m scripts.ingest_local --knowledge-base "$(INGEST_KB)" --root-path "$(INGEST_ROOT)" --dry-run

ingest-check:
	$(UV) run python -m scripts.ingest_check --knowledge-base "$(INGEST_KB)"

index-local:
	$(UV) run python -m scripts.index_local --knowledge-base "$(INGEST_KB)"

index-check:
	$(UV) run python -m scripts.index_check --knowledge-base "$(INGEST_KB)"

retrieve-check:
	$(UV) run python -m scripts.retrieve_check --knowledge-base "$(INGEST_KB)" --query "$(QUERY)"
