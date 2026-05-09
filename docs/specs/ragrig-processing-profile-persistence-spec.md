# RAGRig ProcessingProfile 持久化与变更审计

**版本**: 1.0  
**日期**: 2026-05-09  
**状态**: Implemented  

## 概述

将 ProcessingProfile override 从内存态（`registry.py` 中的 `_OVERRIDE_STORE` dict）迁移到 PostgreSQL 持久化存储，新增变更审计日志表，使服务重启后 override 不丢失，所有变更可追溯。

## 架构设计

### 数据模型

#### processing_profile_overrides

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 主键 |
| profile_id | VARCHAR(255) | UNIQUE | override 标识符 |
| extension | VARCHAR(32) | NOT NULL | 文件扩展名 |
| task_type | VARCHAR(32) | NOT NULL | 任务类型 |
| display_name | VARCHAR(255) | NOT NULL | 显示名称 |
| description | TEXT | NOT NULL | 描述 |
| provider | VARCHAR(128) | NOT NULL | 提供者 |
| model_id | VARCHAR(255) | NULL | 模型 ID |
| status | VARCHAR(32) | NOT NULL DEFAULT 'active' | 状态 |
| kind | VARCHAR(32) | NOT NULL DEFAULT 'deterministic' | 类型 |
| tags | JSONB | NOT NULL DEFAULT '[]' | 标签 |
| metadata_json | JSONB | NOT NULL DEFAULT '{}' | 元数据 |
| created_by | VARCHAR(255) | NULL | 创建者 |
| deleted_at | TIMESTAMPTZ | NULL | 软删除时间 |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL | 更新时间 |

**部分唯一索引**：`CREATE UNIQUE INDEX ON processing_profile_overrides (extension, task_type) WHERE deleted_at IS NULL AND status != 'disabled'`

同一 (extension, task_type) 组合只允许一个 active override。

#### processing_profile_audit_log

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| profile_id | VARCHAR(255) | 关联的 profile ID |
| action | VARCHAR(32) | create / update / delete |
| actor | VARCHAR(255) | 操作者 |
| timestamp | TIMESTAMPTZ | 操作时间 |
| old_state | JSONB | 变更前状态（敏感字段脱敏） |
| new_state | JSONB | 变更后状态（敏感字段脱敏） |

**敏感字段脱敏**：api_key, access_key, secret, session_token, token, password, private_key, credential, dsn, service_account 在审计日志中以 `[REDACTED]` 替代。

### 组件层次

```
main.py (FastAPI routes)
  ├── registry.py (session-aware facade)
  │     ├── in-memory fallback (_OVERRIDE_STORE)
  │     └── DB-backed (when session provided)
  └── repositories/processing_profile.py (DB CRUD + audit)
        └── db/models/entities.py (ORM models)
```

### 向后兼容

- 所有 `registry.py` 函数新增可选 `session` 参数
- 不传 `session` 时回退到原有内存存储
- 现有单元测试无需修改

## API 端点

### 新增

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/processing-profiles/audit-log` | 查询审计日志，支持 `limit`、`profile_id`、`action` 过滤 |

### 修改

所有现有 processing profile 端点现在使用 DB 持久化：

| 方法 | 路径 | 变更 |
|------|------|------|
| GET | `/processing-profiles` | 从 DB 读取 overrides |
| POST | `/processing-profiles` | 写入 DB + 审计日志，冲突返回 409 |
| PATCH | `/processing-profiles/overrides/{id}` | 更新 DB + 审计日志 |
| DELETE | `/processing-profiles/overrides/{id}` | 软删除 + 审计日志 |

## 验证结果

| 验证项 | 状态 |
|--------|------|
| `make lint` | PASS (All checks passed) |
| `make test` | PASS (450 passed, 9 skipped) |
| `make coverage` | PASS (99.47%, >90% threshold) |
| `make web-check` | PASS (52 tests passed) |
| 持久化验证 (重启后 override 不丢失) | PASS (test_persistence_survives_reinitialization) |
| 审计写入 (POST/PATCH/DELETE → audit_log) | PASS (test_audit_log_endpoint_returns_recent_entries) |
| 审计查询 (GET /audit-log) | PASS (test_audit_log_endpoint) |
| 敏感字段脱敏 | PASS (test_audit_log_sanitizes_secrets) |
| 唯一约束 (409 Conflict) | PASS (test_unique_constraint_extension_task_type_conflict) |
| Web Console 显示 | PASS (test_console_html_includes_audit_log_panel, test_console_html_includes_override_meta) |

## 不做边界

- 不提供多租户 RBAC
- 不接 secret 存储
- 不做真实 LLM execution
- 不做远程配置中心
- 不迁移生产历史数据
