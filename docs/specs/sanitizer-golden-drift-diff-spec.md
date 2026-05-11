# SPEC: Sanitizer Golden Drift Diff 与 PR 摘要 (P6)

**Issue**: EVI-78  
**Date**: 2026-05-11  
**Version**: 1.0.0  
**Status**: Implemented  
**Parent**: EVI-72 (Sanitizer Coverage CI Artifact 复盘)

---

## 1. 目标

为 sanitizer golden 文件变更提供自动化 drift diff 工具和 PR reviewer 摘要，快速暴露 parser coverage、redaction_count、degraded 状态的变化。

当 PR 修改了 parser、sanitizer 或敏感 fixture 时，CI 自动比较 base/head 的 `sanitizer-coverage-summary.json`，生成：
- 结构化 diff artifact（JSON）
- Markdown 摘要（PR comment 或 job summary）

---

## 2. Diff Schema

### 2.1 触发条件

Diff 在以下任一情况产生：
- `tests/goldens/sanitizer_*.json` 文件变更
- `scripts/sanitizer_coverage.py` 变更
- `src/ragrig/parsers/` 或 `src/ragrig/parsers/sanitizer.py` 变更
- 任何影响 sanitizer output 的代码变更

CI 在 `coverage` job 已生成 head summary 的基础上，新增 `drift-diff` job 拉取 base branch artifact 并对比。

### 2.2 JSON Schema

```json
{
  "artifact": "sanitizer-drift-diff",
  "version": "1.0.0",
  "generated_at": "2026-05-11T00:00:00+00:00",
  "base_golden_hash": "<sha256>",
  "head_golden_hash": "<sha256>",
  "golden_hash_drift": true,
  "totals": {
    "base": {"fixtures": 4, "redacted": 13, "degraded": 2},
    "head": {"fixtures": 4, "redacted": 11, "degraded": 3},
    "delta": {"fixtures": 0, "redacted": -2, "degraded": 1}
  },
  "risk": "degraded",
  "risk_details": [
    {
      "type": "total_redaction_drop",
      "base": 13,
      "head": 11,
      "delta": -2
    },
    {
      "type": "parser_degraded",
      "parser_id": "parser.csv",
      "reason": "redaction_count dropped or degraded increased"
    }
  ],
  "parsers": {
    "added": [...],
    "removed": [...],
    "changed": [...]
  }
}
```

### 2.3 字段说明

| Field | Type | Description |
|-------|------|-------------|
| `base_golden_hash` | `string` | Base branch aggregate golden hash |
| `head_golden_hash` | `string` | Head branch aggregate golden hash |
| `golden_hash_drift` | `bool` | 聚合 hash 是否变化 |
| `totals.base/head/delta` | `object` | fixtures / redacted / degraded 的 base/head/差值 |
| `risk` | `string` | `degraded` 或 `unchanged` |
| `risk_details` | `array` | 具体退化项列表 |
| `parsers.added` | `array` | 新增 parser 记录 |
| `parsers.removed` | `array` | 移除 parser 记录 |
| `parsers.changed` | `array` | 变更 parser 记录（含 base/head 快照） |

### 2.4 Risk 判定规则

`risk=degraded` 当且仅当以下任一成立：
1. 总 `redacted` 下降（`delta.redacted < 0`）
2. 总 `degraded` 增加（`delta.degraded > 0`）
3. 某个 changed parser 的 `redacted` 下降或 `degraded` 增加
4. 某个 added parser 的 `redacted < 1` 或 `degraded > 0`

否则 `risk=unchanged`。

---

## 3. 安全边界

Diff artifact 和 Markdown report **绝不包含**以下内容：
- 原始 secret 值（`sk-*`、`ghp_*`、Bearer token、private key）
- 完整的 `text_summary`
- 原始文件内容
- JWT token body

生成脚本在写入前执行强制安全检查（`_assert_no_raw_secrets`），若检测到敏感片段则终止并返回错误码 `1`。

Changed parser 记录仅包含以下字段的 base/head 快照：
- `fixtures`
- `redacted`
- `degraded`
- `golden_hash`
- `status`

`degraded_reason`、`csv_parse_error` 等长文本字段 **不进入 diff**，防止间接泄露敏感上下文。

---

## 4. CI 集成

### 4.1 GitHub Actions Job

新增 `drift-diff` job：
1. 检出 base branch（`github.event.pull_request.base.sha`）
2. 运行 `make sanitizer-coverage-summary` 生成 base artifact
3. 检出 head branch
4. 运行 `make sanitizer-coverage-summary` 生成 head artifact
5. 运行 `make sanitizer-drift-diff` 比较两者
6. 上传 `sanitizer-drift-diff.json` 和 `.md` 为 artifact
7. 若 token 权限允许，通过 `gh pr comment` 或 `actions/github-script` 发布 Markdown 摘要
8. 若权限不足，将同等摘要写入 `$GITHUB_STEP_SUMMARY`

### 4.2 Makefile 目标

```makefile
sanitizer-drift-diff:
	$(UV) run python -m scripts.sanitizer_drift_diff \
		--base docs/operations/artifacts/sanitizer-coverage-summary-base.json \
		--head docs/operations/artifacts/sanitizer-coverage-summary.json \
		--output docs/operations/artifacts/sanitizer-drift-diff.json \
		--stdout
```

### 4.3 Artifact 路径

| 路径 | 用途 |
|------|------|
| `scripts/sanitizer_drift_diff.py` | diff 生成脚本 |
| `docs/operations/artifacts/sanitizer-drift-diff.json` | JSON diff artifact |
| `docs/operations/artifacts/sanitizer-drift-diff.md` | Markdown 报告（PR comment / job summary） |
| `tests/test_sanitizer_drift_diff.py` | 测试覆盖 |

---

## 5. 测试验证

### 5.1 Diff 逻辑测试

- `test_drift_no_changes` — 无变更时 risk=unchanged
- `test_drift_parser_added` — 检测新增 parser
- `test_drift_parser_removed` — 检测移除 parser
- `test_drift_redaction_count_dropped_triggers_risk` — redaction 下降触发 degraded
- `test_drift_degraded_increased_triggers_risk` — degraded 增加触发 degraded
- `test_drift_total_redaction_drop_triggers_risk` — 总 redaction 下降触发 degraded
- `test_drift_total_degraded_increase_triggers_risk` — 总 degraded 增加触发 degraded
- `test_drift_golden_hash_drift` — 聚合 hash 漂移检测
- `test_drift_added_parser_zero_redaction_is_risk` — 新增 parser 0 redaction 触发 degraded
- `test_drift_multiple_changes` — 多 parser 同时变更

### 5.2 安全边界测试

- `test_diff_output_never_contains_raw_secrets` — diff 输出不含 secret 片段
- `test_assert_no_raw_secrets_panics` — 安全检查在检测到 secret 时 panic
- `test_render_markdown_no_secrets` — Markdown 输出不含 secret

### 5.3 CLI 测试

- `test_cli_no_changes` — 正常无变更路径，exit 0
- `test_cli_risk_exit_code` — risk=degraded 时 exit 2
- `test_cli_missing_base` — 缺失输入文件时 exit 1
- `test_cli_stdout` — `--stdout` 打印 Markdown
- `test_cli_markdown_only` — `--format markdown` 仅生成 Markdown
- `test_cli_both_outputs` — 默认同时生成 JSON 和 Markdown
- `test_subprocess_invocation` — 子进程调用验证

---

## 6. 验证命令

```bash
# Lint
make lint

# All tests (including drift diff)
make test

# Coverage
make coverage

# Web console check
make web-check

# Generate baseline summary
make sanitizer-coverage-summary

# Run drift diff against itself (no-change baseline)
uv run python -m scripts.sanitizer_drift_diff \
  --base docs/operations/artifacts/sanitizer-coverage-summary.json \
  --head docs/operations/artifacts/sanitizer-coverage-summary.json \
  --stdout
```

---

## 7. 风险与限制

- Golden snapshot 更新后必须审计 diff，确保无意间引入原始 secret
- `golden_hash` 仅反映 golden file 的完整性，不代替实际 security audit
- Diff 不保留历史趋势；长期时序分析需额外存储
- 不做完整 DLP/PII、不接外部安全扫描、不做真实 LLM execution
- PR comment 发布依赖 `GITHUB_TOKEN` 的 `pull-requests: write` 权限；权限不足时降级为 job summary
