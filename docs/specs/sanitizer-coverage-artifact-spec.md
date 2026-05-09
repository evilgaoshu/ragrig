# SPEC: Sanitizer Coverage CI Artifact 与审计摘要 (P5)

**Issue**: EVI-72
**Date**: 2026-05-09
**Version**: 1.0
**Status**: Implemented
**Parent**: EVI-67 (text_summary 脱敏与安全摘要)

## 1. 目标

为 sanitizer golden/coverage 结果生成结构化 CI artifact 和 Web 可视摘要，让 reviewer 快速确认 parser 变更是否引入脱敏风险。

## 2. Artifact Schema

### 2.1 文件

- **CI artifact path**: `docs/operations/artifacts/sanitizer-coverage-summary.json`
- **生成命令**: `make sanitizer-coverage-summary`（运行 `python -m scripts.sanitizer_coverage`）

### 2.2 JSON Schema

```json
{
  "artifact": "sanitizer-coverage-summary",
  "version": "1.0.0",
  "generated_at": "2026-05-09T12:00:00+00:00",
  "totals": {
    "fixtures": 4,
    "redacted": 13,
    "degraded": 2
  },
  "golden_hash": "<sha256 of all parser records>",
  "parsers": [
    {
      "parser_id": "parser.csv",
      "fixtures": 1,
      "redacted": 3,
      "degraded": 1,
      "golden_hash": "<sha256 of golden json>",
      "status": "degraded",
      "degraded_reason": "..."
    }
  ],
  "redaction_floor": 1,
  "redaction_floor_check": true
}
```

### 2.3 审计字段

| Field | Type | Description |
|-------|------|-------------|
| `parser_id` | `string` | Parser identifier (e.g. `parser.csv`) |
| `fixtures` | `int` | Number of golden fixtures for this parser |
| `redacted` | `int` | Total redaction count from golden snapshot |
| `degraded` | `int` | 0 or 1 — whether parser status is "degraded" |
| `golden_hash` | `string` | SHA-256 of the golden file content (deterministic) |
| `status` | `string` | `success` or `degraded` |
| `degraded_reason` | `string?` | Why the parser is degraded (optional) |
| `csv_parse_error` | `string?` | CSV parsing error detail (optional) |

### 2.4 敏感信息边界

Artifact 中**绝不**包含以下内容:
- 原始 secret 值（`sk-*`、`ghp_*`、Bearer token、private key）
- 完整的 `text_summary`（可能含脱敏标记）
- 原始文件内容
- JWT token body

生成脚本在写入前执行强制安全检查（`_assert_no_raw_secrets`），若检测到敏感片段则终止并返回错误码。

## 3. 生成与保留路径

| 路径 | 用途 |
|------|------|
| `scripts/sanitizer_coverage.py` | 生成脚本 |
| `docs/operations/artifacts/sanitizer-coverage-summary.json` | 默认输出路径 |
| `tests/goldens/sanitizer_*.json` | 输入数据源（golden snapshots） |
| `.github/workflows/ci.yml` | CI workflow 的 coverage job 生成并上传 |

## 4. 测试验证

### 4.1 Redaction Floor 测试

`test_redaction_count_below_floor_fails` — 遍历所有 parser/fixture 组合，确保每个 parser 的 `redaction_count >= 1`。低于 floor 则测试失败，防止 sanitizer 退化。

### 4.2 Artifact 安全审计

`test_artifact_never_contains_raw_secrets` — 构建与 CI 输出等价的 artifact 结构，逐寸检查所有字符串是否包含 `sk-`、`ghp_`、`Bearer `、`PRIVATE KEY` 等敏感模式。

### 4.3 Golden 安全审计

`test_goldens_never_contain_secret_fragments` — 读取所有 goldens 文件，检查是否包含 `sk-`、`ghp_`、Bearer token、private key marker 等结构级敏感模式。

### 4.4 Coverage Summary 一致性

`test_coverage_summary_output_consistent_with_golden` — 验证 `pytest -s` 输出的 summary 与 CI artifact 内容一致，打印每 parser 的 redaction/degraded/status。

## 5. Web Console 集成

### 5.1 API 端点

`GET /sanitizer-coverage` — 返回 JSON summary（不含 raw secrets），由 `get_sanitizer_coverage()` 函数生成。

### 5.2 UI 展示

- 侧边栏新增 "Sanitizer Coverage" 导航项
- 新增面板展示表格：Parser ID | Fixtures | Redacted | Degraded | Status | Golden Hash
- 顶部状态 pills 显示：floor check 通过/失败、total parsers、total redactions、total degraded
- 长 parser ID 和 golden hash 使用 `word-wrap: break-word` + `overflow-wrap: break-word` 防止横向溢出和白屏

## 6. 验证命令

```bash
# Lint
make lint

# All tests (包括新增 sanitizer coverage 测试)
make test

# Coverage
make coverage

# Web console check (包括新增 sanitizer-coverage 端点)
make web-check

# 单独生成 sanitizer coverage artifact
make sanitizer-coverage-summary

# 单独运行 sanitizer golden 测试（会打印 coverage summary）
pytest tests/test_sanitizer_golden.py -s
```

## 7. 风险与限制

- Golden snapshot 更新后必须审计 diff，确保无意间引入原始 secret
- `golden_hash` 仅反映 golden file 的完整性，不代替实际 security audit
- 不做完整 DLP/PII、不接外部安全扫描、不做长期 BI/时序存储、不做真实 LLM execution
