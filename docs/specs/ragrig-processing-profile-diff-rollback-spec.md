# RAGRig ProcessingProfile Diff Preview 与回滚

**版本**: 1.0  
**日期**: 2026-05-09  
**状态**: Implemented  
**Issue**: EVI-65

## 概述

为 ProcessingProfile override 实现保存前 diff preview 和基于审计历史的回滚功能。
Web Console 编辑保存前可预览差异，Audit Log 可从可回滚记录触发回滚。

## 架构设计

### API 端点

#### POST /processing-profiles/preview-diff

请求体：

```json
{
  "profile_id": "pdf.chunk.override",
  "display_name": "New Name",
  "provider": "model.ollama"
}
```

响应体：

```json
{
  "old": {
    "profile_id": "pdf.chunk.override",
    "display_name": "Original Name",
    "provider": "deterministic-local",
    ...
  },
  "new": {
    "profile_id": "pdf.chunk.override",
    "display_name": "New Name",
    "provider": "model.ollama",
    ...
  },
  "changed_paths": ["display_name", "provider"]
}
```

- `old` 和 `new` 中包含已脱敏的状态（敏感字段标记为 `[REDACTED]`）
- `changed_paths` 为按字母序排列的变更字段列表，稳定可预测
- override 不存在时返回 404

#### POST /processing-profiles/rollback

请求体：

```json
{
  "audit_id": "<UUID>",
  "actor": "web-console"
}
```

响应体：回滚后的 override profile（同 PATCH 响应格式）

- 基于审计记录的 `old_state`（优先）或 `new_state` 恢复 override
- 写入新的审计日志，action 为 `rollback`，包含 `actor`、`timestamp`、`source_audit_id`
- 恢复后 `GET /processing-profiles/matrix` 反映回滚后的状态

错误处理：
- audit entry 不存在 → 404
- 目标 profile 已删除 → 409
- 目标 profile 已禁用 → 409
- 审计记录无可用状态 → 409

#### GET /processing-profiles/audit-log/{audit_id}

返回单条审计记录的完整详情（含 old_state、new_state），用于回滚前的只读预览。

#### GET /processing-profiles/audit-log 扩展

新增查询参数：
- `provider` — 按 provider 过滤
- `task_type` — 按 task_type 过滤

### 数据库层变更

在 `src/ragrig/repositories/processing_profile.py` 中新增：

- `get_audit_entry_by_id()` — 按 UUID 获取单个审计记录
- `compute_diff()` — 计算当前状态与提议变更的差异
- `rollback_override()` — 基于审计记录执行回滚

回滚审计日志以 `source_audit_id` 字段嵌入 `new_state` JSONB 中，用于追溯回滚来源。

### Web Console

- **Diff Preview Panel**：编辑 override 时显示 before/after 对比
- **Edit 按钮**：在矩阵的 override 单元格中增加 Edit 按钮，打开编辑面板
- **Rollback 按钮**：在审计日志的可回滚记录（create/update，有 old_state）上显示 Rollback 按钮
- **Rollback 二次确认**：使用浏览器 `confirm()` 对话框作为二次确认
- **审计日志过滤器**：支持按 profile_id、provider、task_type 过滤

### 关键验证点

1. `make lint`、`make test`、`make coverage`、`make web-check` 全部通过
2. Diff API 返回 old/new/changed_paths，不包含 secret 明文；changed_paths 顺序稳定（字母序）
3. Rollback API 可基于审计记录恢复上一版本；恢复后 matrix 返回回滚后的 active override
4. 回滚写入新的 audit log，action 为 rollback，包含 actor/timestamp/source_audit_id
5. 已删除、已禁用、不存在 audit target 返回确定性 409/404
6. Web Console 有 diff preview 和 rollback UI；loading/empty/error 不白屏

### Best-Effort 目标

- 按 profile/task/provider 过滤 audit log ✓
- 回滚前二次确认 ✓（confirm 对话框）
- 只读 preview 链接 ✓（GET /processing-profiles/audit-log/{audit_id}）
