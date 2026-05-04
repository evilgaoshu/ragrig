UV ?= uv
ARTIFACTS_DIR ?= docs/operations/artifacts

.PHONY: sync format lint test coverage audit audit-dry-run licenses sbom dependency-inventory supply-chain-check web-check test-db migrate migrate-down db-check db-shell run run-web up down logs ingest-local ingest-local-dry-run ingest-check index-local index-check retrieve-check qdrant-up qdrant-check vector-check

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

coverage:
	$(UV) run pytest --cov --cov-report=term-missing --cov-report=json:coverage.json

audit:
	$(UV) run python -m pip_audit --local --format=json -o "$(ARTIFACTS_DIR)/pip-audit.json"

audit-dry-run:
	$(UV) run python -m pip_audit --local --dry-run

licenses:
	$(UV) run pip-licenses --format=json --output-file "$(ARTIFACTS_DIR)/licenses.json" --partial-match --fail-on "GNU General Public License;Affero General Public License;Server Side Public License;SSPL;source-available" --ignore-packages ragrig

sbom:
	$(UV) run cyclonedx-py environment .venv/bin/python --pyproject pyproject.toml --output-reproducible --of JSON -o "$(ARTIFACTS_DIR)/sbom.cyclonedx.json"

dependency-inventory:
	$(UV) run python -m scripts.dependency_inventory --output docs/operations/dependency-inventory.md

supply-chain-check:
	$(MAKE) licenses && $(MAKE) sbom && $(MAKE) audit

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

qdrant-up:
	docker compose --profile qdrant up -d qdrant

qdrant-check:
	$(UV) run python -m scripts.retrieve_check --knowledge-base "$(INGEST_KB)" --query "$(QUERY)"

vector-check:
	$(MAKE) index-check && $(MAKE) retrieve-check QUERY="$(QUERY)"
