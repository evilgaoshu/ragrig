# SPEC: Sanitizer Drift History 与 Console Badge

## 版本

- **版本**: 1.0.0
- **生效日期**: 2026-05-11
- **所属项目**: ragrig

## 目标

让本地 sanitizer drift diff artifact 支持多版本历史趋势分析，并在 Web Console 展示最新 drift/risk 状态卡片，方便 reviewer 快速判断 sanitizer 质量变化。

## Artifact Schema

### 输入 Artifact

历史分析读取 `docs/operations/artifacts/` 下所有匹配 `sanitizer-drift-diff*.json` 的文件。每份输入必须符合以下 schema：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `artifact` | string | 是 | 必须为 `"sanitizer-drift-diff"` |
| `version` | string | 是 | 语义化版本，当前 `"1.0.0"` |
| `generated_at` | string | 是 | ISO 8601 UTC 时间戳 |
| `base_golden_hash` | string | 是 | base 聚合 hash |
| `head_golden_hash` | string | 是 | head 聚合 hash |
| `golden_hash_drift` | boolean | 是 | hash 是否变化 |
| `totals` | object | 是 | 包含 `base`、`head`、`delta` 子对象 |
| `risk` | string | 是 | `"degraded"` 或 `"unchanged"` |
| `risk_details` | array | 是 | 风险详情列表 |
| `parsers` | object | 是 | 包含 `added`、`removed`、`changed` 数组 |

### 输出 Artifact

脚本 `sanitizer_drift_history.py` 生成 `sanitizer-drift-history.json`，schema 如下：

| 字段 | 类型 | 说明 |
|------|------|------|
| `artifact` | string | `"sanitizer-drift-history"` |
| `version` | string | 工具版本 |
| `schema_version` | string | 与 `version` 一致，用于兼容性校验 |
| `generated_at` | string | 生成时间戳 |
| `status` | string | `"success"`、`"no_history"` 或 `"degraded"` |
| `reports_dir` | string | 扫描的相对目录路径 |
| `trends` | object | 趋势数据（parser/redaction/degraded/risk） |
| `latest` | object \| null | 最新有效报告摘要 |
| `degraded_reports` | array | 损坏/不兼容的报告列表 |

### Console API 返回格式

`GET /sanitizer-drift-history` 返回轻量格式，专供 Web Console 渲染：

| 字段 | 类型 | 说明 |
|------|------|------|
| `available` | boolean | 是否有可用数据 |
| `status` | string | `"success"`、`"no_history"` |
| `risk` | string | 最新 risk 级别 |
| `base_golden_hash` | string | 截断至 12 字符 |
| `head_golden_hash` | string | 截断至 12 字符 |
| `changed_parser_count` | int | 变化的 parser 数量 |
| `added_parser_count` | int | 新增的 parser 数量 |
| `removed_parser_count` | int | 移除的 parser 数量 |
| `head_redacted` | int | 最新 redacted 总数 |
| `head_degraded` | int | 最新 degraded 总数 |
| `generated_at` | string | 最新报告时间 |
| `report_count` | int | 有效报告数量 |
| `sparkline` | object | 最近 10 条 risk/redacted/degraded 序列 |

## Retention 策略

- **存储位置**: `docs/operations/artifacts/`
- **命名约定**: `sanitizer-drift-diff.json` 为最新报告；历史报告可通过后缀区分，如 `sanitizer-drift-diff-20260511.json`
- **清理**: 项目不自动删除历史 artifact； reviewer 可手动清理旧文件，或运行待实现的 `make sanitizer-drift-cleanup`
- **大小限制**: 单份 diff artifact 通常 < 50 KB；历史报告数量建议保留 ≤ 50 份

## Console 展示字段

Web Console `/console` 页面新增 **Sanitizer Drift History** 面板，展示字段：

1. **Risk Level**: 用 pill 颜色区分（degraded=红色，unchanged=绿色，unknown=黄色）
2. **Base / Head Hash**: 截断显示，不展示完整 hash
3. **Changed Parser Count**: 变化、新增、移除的数量
4. **Head Redacted / Degraded**: 最新统计
5. **Trend Sparkline**: 最近 10 条报告的 risk/redacted/degraded 趋势（≥2 份报告时显示）

**不展示的内容**:
- raw secret、Bearer token、private key
- 完整的 golden_hash（仅展示 12 字符前缀）
- parser 级别的详细 diff 内容
- 原始文本或 redacted fragment

## Secret 边界

1. **输入过滤**: 读取 artifact 时不解析或传播任何非 schema 字段的原始文本
2. **输出审计**: 写入 JSON/Markdown 前执行 `_assert_no_raw_secrets`，匹配以下 forbidden fragments：
   - `sk-live-`, `sk-proj-`, `sk-ant-`
   - `ghp_`
   - `Bearer `
   - `PRIVATE KEY-----`
   - `super_secret_db_pass`, `db-super-secret-999`, `prod-api-secret-key-2024`
3. **Console 安全**: API 返回的数据中，hash 被截断，不包含任何 parser 原始内容
4. **降级处理**: 如果 artifact 包含 secret-like 内容导致审计失败，脚本以 exit code 2 退出并报告 `degraded`

## 验证方式

1. `make lint`、`make test`、`make coverage`、`make web-check` 全部通过
2. PR 包含本 SPEC 文档
3. `make sanitizer-drift-history` 可正常执行，输出 JSON + Markdown
4. `/console` 页面展示 drift badge/status card
5. 损坏/不兼容的 artifact 被明确标记为 degraded，不误报 success
6. 单测覆盖：no-history、multi-report trend、corrupt artifact、Console 数据适配、secret-like 泄漏拦截

## 不做边界

- 不接云存储/BI
- 不做 required CI gate
- 不做完整 DLP/PII 扫描
- 不运行真实 LLM

## 相关入口

- `scripts/sanitizer_drift_history.py` — 历史趋势分析脚本
- `scripts/sanitizer_drift_diff.py` — 基础 diff 逻辑
- `src/ragrig/web_console.py` — Console 后端数据适配
- `src/ragrig/web_console.html` — Console 前端展示
- `src/ragrig/main.py` — FastAPI `/sanitizer-drift-history` 端点
- `Makefile` — `sanitizer-drift-history` target
