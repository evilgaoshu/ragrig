# SPEC: Sanitizer Drift History CI Summary Artifact & Console Copy

**Version**: 1.0.0  
**Date**: 2026-05-12  
**Status**: Approved  

---

## 1. 目标

让 sanitizer drift history summary 自动作为 CI artifact 暴露，并在 Console 中提供最新摘要与路径复制功能，减少 reviewer 手动查找 artifact。

---

## 2. CI Artifact 路径与命名

所有 artifacts 位于 `docs/operations/artifacts/` 目录：

| Artifact | 路径 | 说明 |
|----------|------|------|
| Diff JSON | `sanitizer-drift-diff.json` | base vs head 差异 |
| Diff Markdown | `sanitizer-drift-diff.md` | PR comment 摘要 |
| History JSON | `sanitizer-drift-history.json` | 多报告趋势 |
| History Markdown | `sanitizer-drift-history.md` | 趋势 Markdown |
| Summary JSON | `sanitizer-drift-history-summary.json` | 最新摘要 JSON |
| Summary Markdown | `sanitizer-drift-history-summary.md` | PR-ready 摘要 MD |

CI job `drift-diff` 在 PR 事件中:
1. 运行 `sanitizer_drift_diff` → 生成 `sanitizer-drift-diff.*`
2. 运行 `sanitizer_drift_history` → 生成 `sanitizer-drift-history.*`
3. 运行 `sanitizer_drift_history_summary` → 生成 `sanitizer-drift-history-summary.*`
4. 上传 artifacts

---

## 3. Console 字段

`GET /sanitizer-drift-history-summary` 返回:

| 字段 | 类型 | 说明 |
|------|------|------|
| `available` | bool | artifact 是否存在 |
| `status` | string | success / degraded / failure / no_history |
| `latest_risk` | string | unchanged / degraded / unknown |
| `changed_parser_count` | int | changed parser 数量 |
| `degraded_reports_count` | int | 降级报告数量 |
| `valid_report_count` | int | 有效报告数 |
| `total_report_count` | int | 总报告数 |
| `base_golden_hash` | string | base hash |
| `head_golden_hash` | string | head hash |
| `generated_at` | string | ISO8601 生成时间 |
| `summary_path` | string | 相对路径 |
| `summary_json_path` | string or null | JSON 相对路径 |
| `summary_md_exists` | bool | MD 文件是否存在 |
| `reason` | string | 错误原因（仅 failure） |

Console UI 显示:
- Latest status（pill）
- Latest risk（pill）
- Changed parser count
- Degraded reports count
- Valid / total reports
- Summary path（可复制）
- JSON path（可复制）
- Copy Summary 按钮（复制 Markdown 到剪贴板）

---

## 4. Stale / Missing / Corrupt 映射

| 状态 | status | latest_risk | Console 显示 |
|------|--------|-------------|-------------|
| healthy | `success` | `unchanged` | ✅ 绿色 pill |
| degraded | `degraded` | `degraded` | ⚠️ 黄色 pill |
| missing artifact | `no_history` | `unknown` | 中性灰色 |
| corrupt JSON | `failure` | `unknown` | ❌ 红色 pill |
| stale (无新报告) | `success` | `unchanged` | 正常显示 |

missing/corrupt/stale 一律显示 degraded/failure，不误报 success。

---

## 5. Secret 边界

- `_assert_console_no_secrets` 在序列化前审计全部输出
- 禁止出现的 fragment: `sk-live-`, `sk-proj-`, `sk-ant-`, `ghp_`, `Bearer `, `PRIVATE KEY-----`
- 即使输入 artifact 包含 secret-like 片段，summary 不得泄露
- Console HTML 渲染使用 `escapeHtml` + 安全边界检查

---

## 6. 验证方式

1. `make lint`、`make test`、`make coverage`、`make web-check`、`make sanitizer-drift-history-summary` 全部通过
2. PR 包含版本化 SPEC 文档（本文件）
3. CI 产出稳定命名的 summary Markdown/JSON artifact，可从 PR checks 下载
4. `/console` 显示 latest status、latest risk、changed parser count、degraded_reports count、report path，并支持复制 path/summary
5. missing/corrupt/stale artifact 显示 degraded/failure，不误报 success；输出不得包含 secret-like 值
6. 单测覆盖 healthy/degraded/missing/corrupt、copy action、secret 拦截

---

## 7. 最佳实践（best-effort）

PR comment 自动附带摘要 — 由 CI `drift-diff` job 的 `gh pr comment` step 处理。

---

## 8. 不做边界

- 不做 required CI gate
- 不接云存储/BI
- 不运行真实 LLM
- 不改变 history schema

---

## 9. 变更记录

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-05-12 | Initial SPEC |
