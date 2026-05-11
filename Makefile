UV ?= uv
ARTIFACTS_DIR ?= docs/operations/artifacts

.PHONY: sync format lint test coverage audit audit-dry-run licenses sbom dependency-inventory supply-chain-check web-check test-db migrate migrate-down db-check db-shell run run-web up down logs ingest-local ingest-local-dry-run ingest-check index-local index-check retrieve-check qdrant-up qdrant-check vector-check plugins-check s3-check fileshare-check export-object-storage-check minio-up preflight-fileshare-live test-live-fileshare test-live-fileshare-print-evidence fileshare-live-up fileshare-live-down retrieval-benchmark bge-rerank-smoke sanitizer-drift-diff answer-live-smoke understanding-export-diff

INGEST_KB ?= fixture-local
INGEST_ROOT ?= tests/fixtures/local_ingestion
DRIFT_BASE ?= $(ARTIFACTS_DIR)/sanitizer-coverage-summary.json
DRIFT_HEAD ?= $(ARTIFACTS_DIR)/sanitizer-coverage-summary.json

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

answer-live-smoke:
	$(UV) run pytest -m answer_live_smoke

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
	docker compose --profile fileshare-live up -d samba webdav sftp

fileshare-live-down:
	docker compose --profile fileshare-live down --remove-orphans samba webdav sftp

sanitizer-coverage-summary:
	$(UV) run python -m scripts.sanitizer_coverage

eval-local:
	$(UV) run python -m scripts.eval_local

# ── Baseline management ───────────────────────────────────────
# Promote a run to baseline: make eval-baseline RUN_ID=<uuid>
eval-baseline:
	$(UV) run python -m scripts.eval_baseline --run-id "$(RUN_ID)" $(if $(BASELINE_ID),--baseline-id $(BASELINE_ID),)

# ── Retention / cleanup ───────────────────────────────────────
# Clean old evaluation runs: make eval-cleanup KEEP_COUNT=20
eval-cleanup:
	$(UV) run python -m scripts.eval_cleanup $(if $(KEEP_COUNT),--keep-count $(KEEP_COUNT),) $(if $(KEEP_DAYS),--keep-days $(KEEP_DAYS),) $(if $(DRY_RUN),--dry-run,)

# ── Retrieval benchmark ───────────────────────────────────────
# Runs latency measurements for dense/hybrid/rerank/hybrid_rerank
# against the fixture-local knowledge base.  No network, GPU,
# torch, or BGE dependency — fully deterministic and local.
retrieval-benchmark:
	$(UV) run python -m scripts.retrieval_benchmark --pretty

# ── Retrieval benchmark baseline refresh ──────────────────────
# Generates a fresh baseline and manifest from offline fixture data.
# No network, GPU, torch, or BGE dependency.
retrieval-benchmark-baseline-refresh:
	$(UV) run python -m scripts.retrieval_benchmark_baseline_refresh --pretty

# ── Retrieval benchmark baseline compare ──────────────────────
# Compares the current fixture benchmark against a stored baseline.
# No network, GPU, torch, or BGE dependency by default.
# Latency threshold is set high (500%) because local sqlite benchmarks
# are inherently noisy on shared development machines. CI can override
# via BENCHMARK_LATENCY_THRESHOLD_PCT env var.
retrieval-benchmark-compare:
	$(UV) run python -m scripts.retrieval_benchmark_compare --pretty --latency-threshold-pct 500

# ── Optional BGE reranker smoke ────────────────────────────────
# Requires local-ml extras (FlagEmbedding, sentence-transformers,
# torch).  If dependencies are missing the test safely reports
# "skipped" — never a false success.
bge-rerank-smoke:
	$(UV) run python -m scripts.bge_rerank_smoke --pretty

export-object-storage-check:
	$(UV) run python -m scripts.export_object_storage

verify-export-fixture:
	$(UV) run python -m scripts.verify_export_fixture

# ── Sanitizer drift diff ──────────────────────────────────────
# Compares base/head sanitizer-coverage-summary.json artifacts and
# produces a structured diff + Markdown report.  Exit code 2 when
# risk=degraded, 0 when unchanged, 1 on error.
sanitizer-contract-check:
	$(UV) run python -m scripts.sanitizer_contract_check

sanitizer-drift-diff:
	$(UV) run python -m scripts.sanitizer_drift_diff \
		--base $(DRIFT_BASE) \
		--head $(DRIFT_HEAD) \
		--output $(ARTIFACTS_DIR)/sanitizer-drift-diff.json \
		--markdown-output $(ARTIFACTS_DIR)/sanitizer-drift-diff.md \
		--stdout

# ── Sanitizer drift history ───────────────────────────────────
# Reads multiple sanitizer-drift-diff*.json artifacts and produces
# a historical trend report (JSON + Markdown).  Exit code 3 when
# status=degraded, 0 when success/no_history, 2 on safety failure.
sanitizer-drift-history:
	$(UV) run python -m scripts.sanitizer_drift_history \
		--artifacts-dir $(ARTIFACTS_DIR) \
		--output $(ARTIFACTS_DIR)/sanitizer-drift-history.json \
		--markdown-output $(ARTIFACTS_DIR)/sanitizer-drift-history.md \
		--stdout

verify-understanding-export:
	$(UV) run python -m scripts.verify_understanding_export

verify-understanding-export-json:
	$(UV) run python -m scripts.verify_understanding_export --json --output $(ARTIFACTS_DIR)/understanding-export-verify-summary.json

# ── Understanding export baseline diff ────────────────────────
# Compares current understanding export against a baseline fixture/path
# and produces a structured drift/delta report. Exit code 2 when
# status=degraded, 0 when pass, 1 on error/failure.
UNDERSTANDING_DIFF_BASELINE ?= tests/fixtures/understanding_export_contract.json
UNDERSTANDING_DIFF_CURRENT ?= tests/fixtures/understanding_export_contract.json

understanding-export-diff:
	$(UV) run python -m scripts.understanding_export_diff \
		--baseline $(UNDERSTANDING_DIFF_BASELINE) \
		--current $(UNDERSTANDING_DIFF_CURRENT) \
		--output $(ARTIFACTS_DIR)/understanding-export-diff.json \
		--markdown-output $(ARTIFACTS_DIR)/understanding-export-diff.md \
		--stdout
