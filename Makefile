UV ?= uv

.PHONY: sync format lint test test-db migrate migrate-down db-check db-shell run up down logs

sync:
	$(UV) sync --dev

format:
	$(UV) run ruff format .

lint:
	$(UV) run ruff check .

test:
	$(UV) run pytest

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

up:
	docker compose up --build

down:
	docker compose down --remove-orphans

logs:
	docker compose logs -f
