# RAGRig Preview Metadata text_summary 脱敏与安全摘要 Spec (P3)

Date: 2026-05-09
Status: Implemented
Parent: `ragrig-preview-format-parsing-contract-spec.md` (EVI-65) → EVI-66

## 1. Goal

让 preview parser metadata 的 `text_summary` 在保留诊断价值的同时默认脱敏敏感片段，避免文件前缀中的 token、password、api key 等内容进入 pipeline metadata 或 Web Console。

## 2. Verification (Hard Requirements)

1. `make lint`、`make test`、`make coverage`、`make web-check` 全部通过。
2. PR 包含版本化 SPEC 文档，记录脱敏规则、摘要长度、适用 parser、误伤/漏报边界。
3. CSV/HTML/plaintext/markdown preview metadata 共用同一套 summary sanitizer；`api_key`、`password`、`token`、`secret`、Bearer、private key 等样例值不得以明文出现在 `text_summary`。
4. sensitive fixture 覆盖 metadata value 与 `pipeline_run_items` 查询结果，确认 key/value/summary 均不泄露原始 secret 值。
5. 空文件、乱码、超大行、malformed HTML 的 status/degraded_reason 仍确定可复现，summary 长度仍有上限。
6. Web Console 展示脱敏 summary 时不白屏、不横向溢出。

## 3. Best-Effort Goals

- `redaction_count` 字段记录检测到的敏感片段数量。
- 按 parser 的摘要覆盖统计（所有 parser 共用同一 sanitizer）。

## 4. Out of Scope

- 不做完整 DLP/PII 识别。
- 不接外部安全服务。
- 不做 OCR。
- 不做加密密钥管理。
- 不做真实 LLM execution。

## 5. Sanitizer Design

### Module: `src/ragrig/parsers/sanitizer.py`

所有 CSV/HTML/plaintext/markdown preview parser 共用 `sanitize_text_summary(text, max_chars=80)` 函数。

### Detection Patterns (ordered)

| # | Pattern | Example Match | Replacement |
|---|---------|---------------|-------------|
| 1 | Bearer tokens | `Bearer eyJhbGci...` | `Bearer [REDACTED]` |
| 2 | PEM private key blocks | `-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----` | `[PRIVATE KEY REDACTED]` |
| 3 | JSON-style: `"key": "value"` | `"token": "ghp_abc..."` | `"token": "[REDACTED]"` |
| 4 | key=value / key: value (env, YAML, CLI) | `api_key=sk-abc`, `password: admin123`, `db_password=secret` | Preserves key name and separator, replaces value with `[REDACTED]` |
| 5 | Standalone `sk-`/`sk-ant-` prefixed keys (≥5 chars) | `sk-abc12345def` | `[API KEY REDACTED]` |

### Sensitive Key Names

- `api_key`, `apikey`, `api-key`
- `password`
- `secret`
- `token`, `access_token`, `access-token`, `auth_token`, `auth-token`

### Key Design Decisions

- **Key name case preserved**: `API_KEY=prod-secret` → `API_KEY=[REDACTED]` (not lowercased)
- **Prefix-aware**: `db_password=value` → `db_password=[REDACTED]` (matched via `[_-]` before key name)
- **JSON quoted keys**: `"token": "value"` → `"token": "[REDACTED]"` (quotes preserved)
- **Order matters**: key=value patterns (3, 4) run before standalone sk- pattern (5) to avoid double-redaction
- **Truncation after sanitization**: full text is sanitized first, then truncated to 80 chars

### `redaction_count` Field

Each parser metadata now includes `redaction_count: int` — the total number of pattern matches found across the full text (not just the truncated summary prefix).

## 6. Parser Changes

### `TextFileParser` (base)

- Replaced `_text_summary()` with `sanitize_text_summary()`.
- Calls `sanitize_text_summary` once, unpacks `(summary, redactions)`.
- `metadata.redaction_count` added.

### `MarkdownParser` / `PlainTextParser`

- Inherit parent's sanitized `text_summary` and `redaction_count` via `super().parse()`.
- No changes needed.

### `CsvParser`

- Import `sanitize_text_summary` from `sanitizer` module.
- `metadata.redaction_count` added.
- `metadata.text_summary` now sanitized.

### `HtmlParser`

- Import `sanitize_text_summary` from `sanitizer` module.
- `metadata.redaction_count` added.
- `metadata.text_summary` sanitized on stripped text.

## 7. Metadata Schema Update

Added to all parser metadata:

| Field | Type | Description |
|-------|------|-------------|
| `redaction_count` | `int` | Number of sensitive pattern matches found and redacted from the full text. 0 for clean files. |

## 8. Fixture Coverage

### Sensitive Fixture Corpus (parametrized tests)

| Fixture | Parser | Content | Expected Redactions |
|---------|--------|---------|---------------------|
| `api_key_env` | CsvParser | `API_KEY=sk-live-1234567890abcdefghij` | ≥1 |
| `bearer_token` | PlainTextParser | `Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def` | ≥1 |
| `password_config` | PlainTextParser | `db_password=super_secure_db_pass_123` | ≥1 |
| `token_header` | PlainTextParser | `{"token": "ghp_abcdef1234567890"}` | ≥1 |
| `secret_yaml` | MarkdownParser | `secret: prod-api-secret-key-2024` | ≥1 |
| `private_key` | PlainTextParser | PEM block with `-----BEGIN EC PRIVATE KEY-----` | ≥1 |
| `multiple_creds` | CsvParser | `api_key=sk-abc\npassword=pass123\ntoken=secret456` | ≥3 |

### Edge Case Fixtures

| Category | CSV | HTML | Plaintext | Markdown |
|----------|-----|------|-----------|----------|
| empty | ✅ | ✅ | ✅ | ✅ |
| garbled encoding | ✅ | ✅ | — | — |
| oversized line | ✅ | ✅ | ✅ | — |
| malformed | ✅ | ✅ | — | — |

All edge case tests confirm `redaction_count == 0`, bounded summary length (≤81 chars), and stable `status`/`degraded_reason`.

## 9. Risk and Limitations

### False Negatives (Leaks)

- CSV values in columns named after sensitive keys (e.g., `password,value`) where the value is not self-identifying (no `sk-` prefix, no JWT structure).
- Values encoded or obfuscated (e.g., base64-encoded secrets, rot13).
- Very short API keys (<5 alphanumeric chars after `sk-` prefix).

### False Positives (Over-Redaction)

- Legitimate uses of `password`, `token`, `secret` as variable names in documentation where the value is not sensitive (e.g., `token=placeholder`).
- Short `sk-` strings that are not API keys but match the pattern (e.g., `sk-learn` library references — mitigated by requiring ≥5 alphanumeric chars after the prefix).

### Mitigation

- `text_summary` is ≤80 chars, limiting exposure surface.
- Full unredacted text is stored separately in `extracted_text`, not in metadata.
- `redaction_count` provides observability — a non-zero count flags files that triggered sanitization.

## 10. Verification Commands

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
