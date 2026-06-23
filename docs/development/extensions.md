# Extension Tutorial

Use this when adding a small source connector, sink connector, model provider,
or parser adapter. Keep the first patch narrow: config, adapter, registration,
tests, and docs.

## Source Connector Checklist

Use `source.discord` or `source.slack` as the closest template.

1. Add a config model:
   `src/ragrig/plugins/sources/<name>/config.py`
2. Add connector code:
   `src/ragrig/plugins/sources/<name>/connector.py`
3. Add package exports and domain errors:
   `src/ragrig/plugins/sources/<name>/__init__.py`,
   `src/ragrig/plugins/sources/<name>/errors.py`
4. Register the manifest:
   `src/ragrig/plugins/official.py`
5. Add tests:
   `tests/test_<name>_source.py` and `tests/test_plugins.py`

Connector tests must not hit real vendor APIs. Use `httpx.MockTransport`, fake
clients, or local fixtures. Validate:

- config rejects missing required fields
- `env:VAR` secrets resolve through the existing config helpers
- auth/rate-limit/vendor errors map to connector errors
- pagination and aggregation produce stable text documents
- ingestion calls the existing local-directory pipeline or an established
  source ingestion helper
- public report payloads do not expose tokens or secret values

## Model Or Reranker Provider Checklist

Use an existing provider in `src/ragrig/providers/` as the template.

1. Add the provider adapter:
   `src/ragrig/providers/<name>.py`
2. Register it in the provider registry:
   `src/ragrig/providers/__init__.py`
3. Add catalog/manifest metadata when it is user-visible:
   `src/ragrig/providers/model_catalog.py` or `src/ragrig/plugins/official.py`
4. Add settings/env documentation:
   `.env.example` or `docs/operations/optional-services.md`
5. Add tests with fake responses:
   provider unit tests plus retrieval/answer tests when ranking or generation
   behavior changes

Do not add a heavy SDK to the default install path. Prefer `httpx` if the API
is simple; otherwise put the SDK behind an optional extra. Provider traces and
usage metadata should record provider/model/source, never raw secret values.

## Parser Adapter Checklist

Use `src/ragrig/parsers/advanced/docling.py` or `mineru.py` as the template for
optional advanced parsing.

1. Keep local heavy dependencies optional.
2. Add service mode with timeouts and stable degraded metadata where practical.
3. Return structured parser metadata: parser name/version, page/table/image
   counts when available, OCR/layout state, and stable degraded reasons.
4. Update corpus fixtures or mocks under `tests/fixtures/advanced_documents/`.
5. Extend `scripts/advanced_parser_corpus_check.py` when the quality contract
   changes.

Parser failures must not crash ingestion. Return degraded/failure metadata that
can be audited and tested.

## Verification

Run the narrow tests first, then the shared gates:

```bash
uv run pytest tests/test_<changed_area>.py -q
uv run ruff format --check .
uv run ruff check .
```

For frontend-visible changes, also run:

```bash
cd frontend
npm run lint
npm run test:run
npm run build
```
