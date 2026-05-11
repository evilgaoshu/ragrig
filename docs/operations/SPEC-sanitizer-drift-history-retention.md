# SPEC: Sanitizer Drift History PR 摘要与 Artifact Retention

**Version**: 1.0.0  
**Date**: 2026-05-11  
**Status**: Approved

---

## 1. 目标

为 sanitizer drift history 的最新趋势生成 PR 可引用的 Markdown 摘要，并提供安全的 artifact retention/清理入口。

---

## 2. 摘要生成 (`sanitizer-drift-history-summary`)

### 2.1 输入
- `sanitizer-drift-history.json`（由 `sanitizer-drift-history` 生成）

### 2.2 输出
- 紧凑型 Markdown，包含以下字段：
  - `status` — 整体状态（success / degraded / no_history / failure）
  - `latest_risk` — 最新报告的 risk 等级
  - `base_golden_hash` / `head_golden_hash` — 最新报告的 base/head hash
  - `changed_parser_count` — 最新报告中的 changed parser 数量
  - `degraded_reports_count` — 历史扫描中发现的损坏/降级报告数量
  - `report_path` — 输入 history JSON 的相对路径

### 2.3 错误处理
- **缺失文件** → status=`failure`，exit code=1
- **损坏 JSON** → status=`failure`，exit code=1
- **schema 不兼容**（artifact type 或 schema_version 不匹配）→ status=`failure`，exit code=1
- **secret-like 泄漏拦截** → RuntimeError，exit code=2

### 2.4 安全边界
- 输出在序列化前经过 `_assert_no_raw_secrets` 审计
- 禁止出现的 fragment 列表与 `sanitizer_drift_history.py` 保持一致
- 即使输入的 history 包含 secret-like 字符串，summary 也不得将其泄露到输出

---

## 3. Artifact Retention / Cleanup (`artifact-cleanup`)

### 3.1 策略
- 按文件 mtime 排序，支持 `--keep-count`（保留 newest N）和 `--keep-days`（保留 N 天内）
- 两个条件为 **OR** 关系：满足任一条件的文件保留

### 3.2 清理边界
- **默认 dry-run**：只列出将被清理的文件，不执行删除
- **显式确认**：必须提供 `--confirm-delete` 才会真正删除
- 不指定任何 keep 规则时，默认保留全部（安全兜底）

### 3.3 Secret 边界
- 命令输出 JSON 在打印前经过 `_assert_no_raw_secrets` 审计
- 禁止传播 Bearer token、private key、API key 等片段

### 3.4 错误处理
- **目录缺失** → status=`failure`，exit code=1
- **路径不是目录** → status=`failure`，exit code=1

---

## 4. CI / Console 集成（best-effort）

- `make sanitizer-drift-history-summary` 可作为 CI step 运行，输出 PR 可直接引用的 Markdown
- `make artifact-cleanup` 可在定期任务中使用，默认 dry-run 防止误删

---

## 5. 不做边界

- 不接云存储/BI
- 不做 required CI gate
- 不做完整 DLP/PII 扫描（仅覆盖已知 secret fragment 黑名单）
- 不运行真实 LLM

---

## 6. 验证方式

1. `make lint`、`make test`、`make coverage`、`make web-check` 全部通过
2. 单测覆盖：
   - summary generation（valid history）
   - no-history（missing file）
   - corrupt history（bad JSON）
   - retention dry-run（默认不删除）
   - delete guard（无 `--confirm-delete` 不删除）
   - secret-like 泄漏拦截

---

## 7. 变更记录

| Version | Date       | Change            |
|---------|------------|-------------------|
| 1.0.0   | 2026-05-11 | Initial SPEC      |
