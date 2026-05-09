UV ?= uv
ARTIFACTS_DIR ?= docs/operations/artifacts

.PHONY: sync format lint test coverage audit audit-dry-run licenses sbom dependency-inventory supply-chain-check web-check test-db migrate migrate-down db-check db-shell run run-web up down logs ingest-local ingest-local-dry-run ingest-check index-local index-check retrieve-check qdrant-up qdrant-check vector-check plugins-check s3-check fileshare-check export-object-storage-check minio-up preflight-fileshare-live test-live-fileshare test-live-fileshare-print-evidence fileshare-live-up fileshare-live-down

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

test-unit:
	$(UV) run pytest -m unit

test-integration:
	$(UV) run pytest -m integration

test-smoke:
	$(UV) run pytest -m smoke

test-live:
	$(UV) run pytest -m live

test-fast:
	$(UV) run pytest -m "not live and not slow"

test-optional:
	$(UV) run pytest -m optional

coverage:
	$(UV) run pytest --cov --cov-report=term-missing --cov-report=json:coverage.json

coverage-strict:
	$(UV) run pytest --cov=ragrig.chunkers --cov=ragrig.embeddings --cov=ragrig.retrieval --cov=ragrig.acl --cov-fail-under=100 --cov-report=term-missing

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

plugins-check:
	$(UV) run python -m scripts.plugins_check --format json

minio-up:
	docker compose --profile minio up -d minio

s3-check:
	$(UV) run python -m scripts.s3_check

fileshare-check:
	$(UV) run python -m scripts.fileshare_check

preflight-fileshare-live:
	$(UV) run python -m scripts.preflight_fileshare_live

test-live-fileshare:
	$(UV) run python -m scripts.test_live_fileshare

test-live-fileshare-print-evidence:
	$(UV) run python -m scripts.test_live_fileshare --print-evidence

fileshare-live-up:
	docker compose --profile fileshare-live up -d

fileshare-live-down:
	docker compose --profile fileshare-live down --remove-orphans

sanitizer-coverage-summary:
	$(UV) run python -m scripts.sanitizer_coverage

export-object-storage-check:
	$(UV) run python -m scripts.export_object_storage

verify-export-fixture:
	$(UV) run python -m scripts.verify_export_fixture
