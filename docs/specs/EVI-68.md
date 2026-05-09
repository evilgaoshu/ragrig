# EVI-68: Understanding Runs 导出与过滤

**版本**: 1.0
**日期**: 2026-05-09
**状态**: Implemented

## 目标

让 DocumentUnderstanding run history 支持可审计导出与常用过滤，方便问题复盘和对比分析。

## 功能范围

### API 过滤

- `/knowledge-bases/{kb_id}/understanding-runs` 新增 `started_after` / `started_before` 时间范围过滤参数
- `/understanding-runs` (Web Console) 同步支持所有过滤参数：`provider`, `model`, `profile_id`, `status`, `started_after`, `started_before`, `limit`
- 结果始终按时间倒序排列
- `UnderstandingRunFilter` schema 包含所有过滤字段

### 安全 JSON 导出

- `GET /understanding-runs/{run_id}/export` — 导出单个 run（安全 JSON）
- `GET /knowledge-bases/{kb_id}/understanding-runs/export` — 导出过滤后的 run 列表（安全 JSON）
- 导出器自动清理以下内容：
  - 敏感字段 key（`extracted_text`, `prompt`, `full_prompt`, `system_prompt`, `user_prompt`, `messages`, `raw_response`）→ `[REDACTED]`
  - 密钥类字段（`api_key`, `access_key`, `secret`, `session_token`, `token`, `password`, `private_key`, `credential`）→ `[REDACTED]`
  - 递归处理嵌套 dict/list
- 导出包含 `exported_at` 时间戳和 `filters_applied` 元数据

### Web Console 过滤控件

- Understanding Runs 面板新增过滤栏：
  - Provider 下拉（自动填充）
  - Profile 下拉（自动填充）
  - Status 下拉（预定义值）
  - 开始时间 after/before（datetime-local 输入）
  - Limit 下拉（5/10/20/50）
- 过滤参数变更即时触发重新渲染
- 面板头部新增「⬇ Export」按钮，按当前过滤条件导出列表
- 每个 run card 新增「⬇ Export」按钮，导出单个 run

### Run Diff（best-effort）

- `GET /understanding-runs/{run_id}/diff?against=<run_id>` — 比较两个 run
- 返回结构化的 field-by-field 差异（含 `delta` 数值差）
- HTML 预留 diff 面板（`#understanding-runs-diff`）

## 验证方式

1. `make lint` 全部通过
2. `make test` 全部通过（527 tests passed, 9 skipped）
3. `make coverage` 通过，覆盖率 99.43%（> 90%）
4. `make web-check` 全部通过（64 tests passed）
5. API 支持按 provider/model/profile/status/time range 过滤 runs，结果按时间倒序
6. 单个 run 与列表支持安全 JSON 导出，不泄露 secret/完整 prompt/完整原文
7. Web Console 提供过滤控件与导出入口，loading/empty/error 不白屏、不横向溢出

## 不做边界

- 不做多租户 RBAC
- 不做长期归档
- 不做 BI 报表
- 不做云端 live smoke

## 实现细节

### 修改文件

| 文件 | 改动 |
|------|------|
| `src/ragrig/understanding/schema.py` | `UnderstandingRunFilter` 新增 `started_after` / `started_before` |
| `src/ragrig/understanding/service.py` | 新增时间范围过滤、`export_understanding_run()`、`export_understanding_runs()`、`compare_understanding_runs()`、`_sanitize_value()` |
| `src/ragrig/understanding/__init__.py` | 导出新函数 |
| `src/ragrig/web_console.py` | `list_understanding_runs()` 支持全部过滤参数 |
| `src/ragrig/main.py` | 新增导出/diff 端点，更新时间范围参数 |
| `src/ragrig/web_console.html` | 新增过滤栏 CSS、过滤控件 JS、导出按钮、downloadJson 工具函数 |
| `tests/test_understanding.py` | 新增 17 个测试覆盖时间过滤、安全导出、diff |

### 安全导出设计

`_sanitize_value()` 递归处理 dict/list：
- 黑名单 key（`_EXPORT_SENSITIVE_KEYS`）→ REDACTED
- 密钥类 key + 非空值 → REDACTED
- 其他值保留

### 导出文件名

- 单个 run：`ragrig-run-{kb_name}-{run_id[:8]}.json`
- 列表：`ragrig-runs-{kb_name}-{ISO timestamp}.json`
