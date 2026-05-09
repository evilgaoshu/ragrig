# RAGRig Preview Metadata Sanitizer Golden Snapshot & Coverage Spec

**Version**: 1.0.0
**Created**: 2026-05-09
**Parent Issue**: EVI-70
**Status**: Implemented

## 1. Purpose

Establish a golden-snapshot regression suite and coverage summary for the
preview metadata sanitizer (`ragrig.parsers.sanitizer`).  When parser
behaviour or sanitizer patterns change, the golden tests fail with a clear
diff, preventing silent sanitization regressions.

## 2. Golden Fixture Scope

### 2.1 Parser Coverage

Golden snapshots exist for every parser that uses `sanitize_text_summary`:

| Parser        | Fixture                | Golden File                            |
|---------------|------------------------|----------------------------------------|
| CsvParser     | `sensitive.csv`        | `sanitizer_csv_sensitive.json`         |
| HtmlParser    | `sensitive.html`       | `sanitizer_html_sensitive.json`        |
| PlainTextParser | `sensitive.txt`      | `sanitizer_plaintext_sensitive.json`   |
| MarkdownParser | `sensitive.md`        | `sanitizer_markdown_sensitive.json`    |

### 2.2 Fixture Contents

Each sensitive fixture contains at least one secret-bearing pattern:

- **CSV**: `api_key` column with `sk-` values, password column
- **HTML**: `<script>` with `API_KEY`, `<pre>` with `AWS_SECRET_ACCESS_KEY`
- **Plaintext**: `api_key=`, `ACCESS_TOKEN=`, `password =`, `Bearer` token
- **Markdown**: YAML frontmatter `secret:`, `database_password:`, bare `sk-`
  keys, PEM private key block

### 2.3 Golden JSON Schema

```json
{
  "parser_id": "parser.csv",
  "status": "degraded",
  "text_summary": "name,api_key,password,email\nadmin,[API KEY REDACTED],...",
  "redaction_count": 3,
  "degraded_reason": "Parsed as plain text; ..."
}
```

Fields:

| Field              | Type    | Required | Description                                   |
|--------------------|---------|----------|-----------------------------------------------|
| `parser_id`        | string  | Yes      | Parser identifier (e.g. `parser.csv`)         |
| `status`           | string  | Yes      | `success` or `degraded`                       |
| `text_summary`     | string  | Yes      | Truncated (≤81 chars), redacted summary       |
| `redaction_count`  | int     | Yes      | Number of pattern matches redacted            |
| `degraded_reason`  | string  | No       | Present when `status == "degraded"`           |
| `csv_parse_error`  | string  | No       | Present when csv.reader throws                |

**Secrecy invariant**: No golden file on disk may contain raw secret
values (`sk-*` keys, bearer tokens, PEM private key bodies, password
values, etc.).  A dedicated audit test (`test_golden_snapshots_never_contain_raw_secrets`)
enforces this at CI time.

## 3. Snapshot Update Flow

When the sanitizer behaviour intentionally changes (new patterns, pattern
adjustments, truncation changes):

```bash
python -m scripts.snapshot_update
```

This re-parses every sensitive fixture and overwrites the golden JSON files.
Review the diff (`git diff tests/goldens/`) before committing.

### 3.1 What Triggers a Golden Update

- Adding or removing sanitizer patterns in `sanitizer.py`
- Changing `_MAX_CHARS` truncation limit
- Changing parser metadata that flows into the golden record (`parser_id`,
  `status`, `degraded_reason`)
- Changing the format of sensitive fixture files

### 3.2 What Does NOT Trigger a Golden Update

- Changes to non-sanitizer code paths
- Changes to parsers that do not use `sanitize_text_summary`
- Changes to web console layout

## 4. Coverage Summary

The `test_sanitizer_coverage_summary` test produces a per-parser summary:

```
── Sanitizer Coverage Summary ──
Parser ID                 Fixtures   Redacted   Degraded
---------------------------------------------------
parser.csv                       1          3          1
parser.html                      1          1          1
parser.text                      1          4          0
parser.markdown                  1          5          0
---------------------------------------------------
TOTAL                            4         13          2
```

### 4.1 Regression Guarantees

- **Fixture count**: Must equal 4.  If a parser's fixture goes missing, the
  test fails.
- **Redaction floor**: Every parser must have `redaction_count >= 1`.  A
  zero-count means the sensitive fixture no longer triggers any pattern,
  indicating a regression.
- **Golden field match**: All required fields (`parser_id`, `status`,
  `text_summary`, `redaction_count`) must match byte-for-byte against the
  golden file.

## 5. False Positive Handling

A golden mismatch can be:

1. **Intentional change**: The sanitizer patterns were updated.  Run
   `scripts/snapshot_update.py`, review the diff, commit.
2. **Fixture changed**: A sensitive fixture file was edited, changing the
   expected redaction count or text_summary.  Run snapshot_update and
   verify the new fixture still contains secrets.
3. **Parser behaviour changed**: A parser now produces different metadata
   (different `parser_id`, `status`, etc.).  Update the golden file or
   revert the parser change depending on intent.

## 6. Web Console Safety

The web console debug/overview views now display `redaction_count` and
`text_summary` inline.  CSS protections prevent:

- **White-screen**: All metadata values are escaped with `escapeHtml()`.
  `null`/`undefined` checks prevent `toString()` on missing values.
- **Horizontal overflow**: `.meta-summary-cell` uses `overflow: hidden`,
  `text-overflow: ellipsis`, `white-space: nowrap`, `max-width: 100%`.
  Existing `.sub` and `td` rules use `overflow-wrap: anywhere`.

## 7. CI Integration

The golden tests run as part of `make test` (unit marker).  `make coverage`
includes the golden tests in coverage reporting.  Test files are:

- `tests/test_sanitizer_golden.py` — golden regression + coverage summary
- `tests/goldens/*.json` — checked-in golden snapshots
- `scripts/snapshot_update.py` — snapshot regeneration CLI

## 8. Out of Scope

- Full DLP/PII detection (this is a preview metadata sanitizer only)
- External security services
- Real LLM execution
- Golden snapshots for non-preview parsers (PDF, DOCX, etc.)
- Runtime DLP classification of extracted text
