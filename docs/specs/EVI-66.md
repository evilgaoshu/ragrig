# RAGRig Preview Parser Fixture Corpus & Degradation Quality Gate Spec (P2)

Date: 2026-05-09
Status: Implemented
Parent: `ragrig-preview-format-parsing-contract-spec.md` (EVI-65)

## 1. Goal

让 preview parser 的降级行为有稳定 fixture 语料、质量摘要和回归门，避免 CSV/HTML 等 preview 格式后续扩展时静默退化或泄露内容。

## 2. Verification (Hard Requirements)

1. `make lint`、`make test`、`make coverage`、`make web-check` 全部通过。
2. PR 包含版本化 SPEC 文档，记录 fixture 范围、parser metadata schema、降级判定和安全边界。
3. 新增 CSV/HTML fixture corpus，覆盖空文件、乱码/编码、超大行、malformed HTML、敏感字段样例；测试不依赖外网。
4. parser metadata 返回稳定字段：`parser_id`、`status`、`degraded_reason`、size/row/column 或文本摘要指标；不得返回完整原文或 secret。
5. 上传 preview fixture 后 `pipeline_run_items` 可查询到同一套 metadata；超时/超限/解析异常状态确定且可复现。
6. Web Console 对 fixture 触发的 degraded/failed 状态不白屏、不横向溢出。

## 3. Best-Effort Goals

- golden JSON 快照。
- parser quality summary。
- 按 extension 的 fixture 覆盖统计。

## 4. Out of Scope

- 不做 OCR。
- 不接云端解析服务。
- 不实现完整 PDF/Office 解析。
- 不做真实 LLM execution。

## 5. Parser Metadata Schema

All parsers return a `ParseResult` with `metadata` containing the following stable fields:

### Required fields (always present)

| Field | Type | Description |
|-------|------|-------------|
| `parser_id` | `str` | Stable parser identifier, e.g. `"parser.csv"`, `"parser.html"`, `"parser.markdown"`, `"parser.text"` |
| `status` | `str` | `"success"` for fully-supported formats, `"degraded"` for preview formats |
| `encoding` | `str` | Source encoding, e.g. `"utf-8"` |
| `extension` | `str` | Lowercase file extension including dot, e.g. `".csv"` |
| `line_count` | `int` | Number of lines in the file (0 for empty) |
| `char_count` | `int` | Total character count |
| `byte_count` | `int` | Total byte count of the raw file |
| `text_summary` | `str` | First 80 characters of parsed text (truncated with `…` if longer) |

### Conditional fields

| Field | Type | Condition | Description |
|-------|------|-----------|-------------|
| `degraded_reason` | `str` | `status == "degraded"` | Human-readable reason for degradation |
| `row_count` | `int` | CSV parser | Best-effort row count from `csv.reader` |
| `col_count` | `int` | CSV parser | Best-effort column count from `csv.reader` |
| `stripped_char_count` | `int` | HTML parser | Character count after tag stripping |
| `csv_parse_error` | `str` | CSV parse failure | Error detail when `csv.reader` raises an exception |

### Security boundaries

- Metadata MUST NOT contain the full original file text.
- Metadata MUST NOT contain secret-like key names (`api_key`, `password`, `secret`, `token`, `credential`).
- `text_summary` is truncated to 80 characters and may incidentally include sensitive content from the first 80 characters; this is accepted as a best-effort preview.
- Full original text is stored separately in `DocumentVersion.extracted_text`, not in metadata.

## 6. Fixture Corpus

### Directory: `tests/fixtures/preview/`

| File | Format | Category | Description |
|------|--------|----------|-------------|
| `empty.csv` | CSV | empty | 0-byte CSV file |
| `empty.html` | HTML | empty | 0-byte HTML file |
| `sensitive.csv` | CSV | sensitive fields | CSV with `api_key`, `password`, `email` columns containing realistic secrets |
| `sensitive.html` | HTML | sensitive fields | HTML with `script` tag containing `API_KEY`, `<pre>` with AWS/DATABASE credentials |
| `malformed.html` | HTML | malformed | Unclosed tags, missing `</head>`, unclosed `<!--` comment, XSS patterns |
| `garbled.csv` | CSV | encoding | Valid CSV header/row followed by binary `\x80\x81\x82\xFE\xFF` line (UTF-8 decode fails) |
| `garbled.html` | HTML | encoding | Valid HTML start followed by binary garbage (`\xFE\xFF\x00\x01`) |
| `binary_garbled.csv` | CSV | encoding | Entirely binary content that cannot be decoded as UTF-8 |
| `binary_garbled.html` | HTML | encoding | Entirely binary content that cannot be decoded as UTF-8 |
| `oversized_line.csv` | CSV | large row | CSV with a ~500KB single field value in one row |

### Coverage by category

| Category | CSV | HTML |
|----------|-----|------|
| empty | ✅ | ✅ |
| sensitive fields | ✅ | ✅ |
| malformed | — | ✅ |
| garbled encoding | ✅ | ✅ |
| large row/document | ✅ | ✅ |

## 7. Pipeline Run Items Metadata

When a preview fixture is uploaded:

- `status`: `"degraded"` for CSV/HTML (parser reports `degraded_reason`), `"failed"` for encoding failures or timeouts.
- `metadata.parser_id`: Stable identifier matching the parser used.
- `metadata.parser_name`: Short name (e.g. `"csv"`, `"html"`).
- `metadata.degraded_reason`: Present when status is `"degraded"`.
- `metadata.failure_reason`: Present when status is `"failed"` (e.g. `"parser_timeout"` or decode error details).
- `error_message`: The original exception message for failed items.

All statuses are deterministic and reproducible — the same fixture file always produces the same status and error metadata.

## 8. Web Console Design Rules

The Web Console HTML/CSS already includes:

- `overflow-wrap: anywhere` on code, fact-value, collection-name, pill, td, th elements.
- `overflow-x: auto` / `-webkit-overflow-scrolling: touch` on scrollable containers.
- Responsive grid layout that collapses to single column at 1100px.
- `word-break` via `overflow-wrap` handles long words/monospace text.

These rules ensure that:
- Status pills (`pill warn`, `pill error`) for degraded/failed items do not overflow.
- Long `degraded_reason` or `error_message` text wraps rather than expanding the viewport.
- No white screen occurs when pipeline data contains errors.

## 9. Parser Changes

### `TextFileParser` (base)

- Added `_text_summary()` helper: returns first 80 characters with ellipsis truncation.
- `metadata` now includes: `parser_id`, `status`, `byte_count`, `text_summary`.

### `MarkdownParser` / `PlainTextParser`

- Override `parse()` to add `parser_id` and `status="success"` to parent metadata.

### `CsvParser`

- `metadata` now includes: `parser_id="parser.csv"`, `status="degraded"`, `byte_count`, `text_summary`.
- Added `csv_parse_error` field when `csv.reader` raises an exception.

### `HtmlParser`

- `metadata` now includes: `parser_id="parser.html"`, `status="degraded"`, `byte_count`, `text_summary`.

## 10. Risk and Limitations

- `text_summary` truncation at 80 characters is a best-effort preview; sensitive content in the first 80 characters of a file may appear.
- Binary/garbled files cause `UnicodeDecodeError` which is caught by the pipeline as a `failed` status.
- CSV parser row/column counts are best-effort and fall back to 0 on malformed input.
- Oversized line fixture (~500KB single field) is tested at parser level; upload endpoint tests use smaller files for speed.

## 11. Verification Commands

```bash
# Lint
make lint

# All tests
make test

# Coverage
make coverage

# Web console checks
make web-check
```
