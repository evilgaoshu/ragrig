# RAGRig Preview Format Parsing Contract and Upload Degradation Governance Spec

Date: 2026-05-09
Status: Implemented

## 1. Goal

让浏览器上传对 preview/planned/unsupported 格式的后续处理可解释、可回放：preview 文件要么通过明确 parser/fallback 进入 pipeline，要么以结构化 degraded/failed 状态结束，不能静默成功或白屏。

## 2. Verification (Hard Requirements)

1. `make lint`、`make test`、`make coverage`、`make web-check` 全部通过。
2. `supported-formats` 中每个 preview extension 返回 `parser_id`、`status=preview`、`fallback_policy` 或等价字段。
3. 上传至少 1 个 preview fixture 后返回非空 `pipeline_run_id`，并可查询到对应 `pipeline_run_items` 的 parser/status/error 或 degraded 原因。
4. planned/unsupported 格式仍返回 HTTP 415，`.rejections[0].reason=unsupported_format`。
5. Web Console 对 preview 上传显示 warning、pipeline 状态和失败/降级原因；页面不白屏、不横向溢出。
6. 日志/API/Console 不泄露 secret、完整原文或完整 prompt。

## 3. Best-Effort Goals

- 增加一个轻量 preview parser（如 CSV/HTML）或 PDF text extraction spike。
- 增加 per-format size limit 与 parser timeout 测试。

## 4. Out of Scope

- 不做 10-100MB chunked upload。
- 不做 OCR。
- 不接云端解析服务。
- 不做 ACL/RBAC。
- 不实现完整 DocumentUnderstanding。

## 5. Data Model Changes

### `SupportedFormat`

新增字段：

```python
fallback_policy: str | None = None
"""What happens when this preview format fails or degrades,
   e.g. 'parse_as_plaintext'."""
```

### `PipelineRunItem` (metadata_json)

上传成功后，pipeline run item 的 `metadata_json` 中记录：

- `parser_id`: e.g. `"parser.csv"`
- `parser_name`: e.g. `"csv"`
- `degraded_reason`: 当解析以降级方式完成时记录原因
- `failure_reason`: 当解析失败时记录原因

## 6. Format Registry Updates

`supported_formats.yaml` 和硬编码 defaults 中，所有 preview 扩展名新增 `fallback_policy`：

| Extension | Parser ID | Fallback Policy |
|-----------|-----------|-----------------|
| `.rst` | `parser.text` | `parse_as_plaintext` |
| `.csv` | `parser.csv` | `parse_as_plaintext` |
| `.json` | `parser.text` | `parse_as_plaintext` |
| `.xml` | `parser.text` | `parse_as_plaintext` |
| `.html` | `parser.html` | `strip_tags_then_plaintext` |

## 7. Preview Parsers

### `CsvParser`

- 继承 `TextFileParser`
- 提取原始文本 + 最佳努力的行/列计数
- 解析失败时不抛出异常，降级为纯文本
- `metadata.degraded_reason`: "Parsed as plain text; CSV structure awareness not implemented."

### `HtmlParser`

- 继承 `TextFileParser`
- 使用正则 strip HTML tags，折叠空白字符
- `metadata.degraded_reason`: "HTML tags stripped; structure and links are lost."

## 8. Parser Timeout Guard

- `parse_with_timeout(parser, path, timeout_seconds=30.0)` 使用 `ThreadPoolExecutor` 对 parser 调用设置超时。
- 超时抛出 `ParserTimeoutError`，pipeline run item 状态为 `failed`，`failure_reason="parser_timeout"`。

## 9. Upload Endpoint Behavior

### 格式校验

- 未知扩展名 → 415，`reason="unsupported_format"`
- `PLANNED` 扩展名 → 415，`reason="unsupported_format"`
- `PREVIEW` 扩展名 → 接受，在 `warnings` 中返回 `parser_id` + `fallback_policy`

### 大小限制

- 使用 `fmt.max_file_size_mb` 作为每个格式的大小上限（而非固定 10MB）。
- 超限 → 413，`reason="file_too_large"`，message 包含格式名和具体限制。

### Pipeline 记录

- 解析成功且无降级 → `status="success"`
- 解析成功但 parser 报告 `degraded_reason` → `status="degraded"`
- 解析超时 → `status="failed"`，`error_message` 为超时信息
- 其他异常 → `status="failed"`，`error_message` 为异常信息

## 10. Web Console Updates

- 上传结果区域展示 `Warnings` 卡片（含 `parser_id` + `fallback_policy`）。
- 上传成功后自动拉取 `/pipeline-runs/{id}/items` 并展示 `Pipeline Items`（含 parser、status、degraded/failure reason）。
- Pipeline Runs 面板展示每个 item 的 parser 和 degraded 信息。
- 现有响应式布局未改动，无白屏/横向溢出风险。

## 11. Verification Commands

```bash
# Lint
make lint

# Tests
make test

# Coverage (100% gate)
make coverage

# Web console checks
make web-check
```

## 12. Risk and Limitations

- CSV/HTML parser 均为轻量实现，不处理复杂编码、嵌套结构或大型文件流式读取。
- Timeout guard 基于线程池，极端 I/O 阻塞场景下仍可能无法精确中断。
- `fallback_policy` 为新增可选字段，现有 API 消费者不受影响。
