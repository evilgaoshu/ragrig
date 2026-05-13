# SPEC: Understanding Export Diff PR 摘要与 Artifact Retention (EVI-98)

**Version**: 1.0.0
**Date**: 2026-05-12
**Status**: Approved

---

## 1. 目标

为 understanding-export-diff 生成 PR 可引用的 Markdown 摘要，并提供安全的 artifact retention/清理入口。

---

## 2. 摘要生成 (`understanding-export-diff-summary`)

### 2.1 摘要字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | `pass` / `degraded` / `failure` | 整体状态 |
| `baseline_run_count` | int | baseline run 数量 |
| `current_run_count` | int | current run 数量 |
| `added_count` | int | 新增 run 数量 |
| `removed_count` | int | 移除 run 数量 |
| `changed_count` | int | 变更 run 数量 |
| `schema_compatible` | bool | schema 版本是否兼容 |
| `generated_at` | string (ISO8601) | diff 报告生成时间 |
| `json_report_path` | string | JSON 报告相对路径 |
| `md_report_path` | string | Markdown 报告相对路径 |

### 2.2 输入

- `understanding-export-diff.json`（由 `understanding-export-diff` 生成）
- 可选：companion Markdown 报告路径（自动解析为同名 `.md` 文件）

### 2.3 输出

- 紧凑型 Markdown，包含状态 emoji、变更计数、artifact 路径等

### 2.4 错误处理

- **缺失文件** → status=`failure`，exit code=1
- **损坏 JSON** → status=`failure`，exit code=1
- **artifact type 不匹配** → status=`failure`，exit code=1
- **version 不匹配** → status=`failure`，exit code=1
- **secret-like 泄漏拦截** → RuntimeError，exit code=2

### 2.5 安全边界

- 输出在序列化前经过 `_assert_no_raw_secrets` 审计
- 禁止出现的 fragment 列表与 `understanding_export_diff.py` 保持一致
- 即使输入的 diff artifact 包含 secret-like 字符串，summary 也不得将其泄露到输出

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

- `make understanding-export-diff-summary` 可作为 CI step 运行，输出 PR 可直接引用的 Markdown
- `make artifact-cleanup` 可在定期任务中使用，默认 dry-run 防止误删

---

## 5. 不做边界

- 不接云存储/BI
- 不做 required CI gate
- 不做完整 DLP/PII 扫描（仅覆盖已知 secret fragment 黑名单）
- 不运行真实 LLM
- 不改变 export v1 schema

---

## 6. 验证方式

1. `make lint`、`make test`、`make coverage`、`make web-check`、`make understanding-export-diff` 全部通过
2. 单测覆盖：
   - summary 输出在 pass / degraded / failure 三种状态下格式正确
   - 缺失或损坏 artifact 输入时 summary 输出 failure 状态
   - cleanup dry-run 默认不删除文件、confirm-delete 才删除（复用 artifact_cleanup 测试）
   - secret-like 泄漏拦截（summary 输出不包含 raw prompt、完整原文或 secret fragment）

---

## 7. 变更记录

| Version | Date       | Change            |
|---------|------------|-------------------|
| 1.0.0   | 2026-05-12 | Initial SPEC      |
