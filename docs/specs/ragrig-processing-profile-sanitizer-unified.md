# ProcessingProfile metadata sanitizer — 单一来源与漂移防护

**版本**: 1.0  
**日期**: 2026-05-09  
**状态**: Implemented  
**Issue**: EVI-74

## 概述

将 ProcessingProfile 相关 metadata sanitizer 的敏感 key/value 规则统一为单一实现来源
(`ragrig.processing_profile.sanitizer`)，消除 repository 和 model 层之间的重复逻辑，
并用测试防止规则漂移。

## 共享 helper 入口

**模块**: `src/ragrig/processing_profile/sanitizer.py`

### 公开 API

| 函数 | 签名 | 用途 |
|------|------|------|
| `is_sensitive_key` | `(key: str) -> bool` | 判断 key 名是否含敏感词 |
| `is_sensitive_value` | `(value: object) -> bool` | 判断标量值是否像 secret (Bearer/PEM) |
| `redact_metadata` | `(dict, prefix="") -> (dict, int, list[str])` | **redacted 模式**：替换为 `[REDACTED]`，返回 (结果, 脱敏数, 路径) |
| `remove_metadata` | `(dict) -> dict` | **removal 模式**：删除敏感字段，仅返回干净 dict |
| `redact_state` | `(dict, metadata_key="metadata_json") -> dict` | 审计日志 state 脱敏，附加 `_redaction` 元数据 |

### 共享配置 (canonical)

```python
REDACTED = "[REDACTED]"

SENSITIVE_KEY_PARTS = (
    "api_key", "access_key", "secret", "session_token",
    "token", "password", "private_key", "credential",
    "dsn", "service_account",
)

SENSITIVE_VALUE_PREFIXES = (
    "bearer ",
    "-----begin",
)
```

**修改此配置即自动影响所有调用点。**

## 两种输出模式

### Redacted 模式 (`redact_metadata`)

- 敏感字段值替换为 `[REDACTED]`
- 返回 `(sanitized_dict, redaction_count, redacted_paths)`
- 保持字段存在性，适合审计日志 (`old_state`/`new_state`)

**调用点**:
- `repositories/processing_profile.py` — `_sanitize_metadata_json()` (wrapper)
- `repositories/processing_profile.py` — `_sanitize_state()` (wrapper)
- 通过 `_write_audit_log()` → `_sanitize_state()` 用于 create/update/delete/rollback 审计
- 通过 `compute_diff()` → `_sanitize_state()` 用于 diff preview

### Removal 模式 (`remove_metadata`)

- 敏感字段完全从输出中删除
- 不保留字段 key
- 适合 API 响应载荷 (`to_api_dict`)

**调用点**:
- `processing_profile/models.py` — `_sanitize_metadata()` (wrapper)
- 通过 `ProcessingProfile.to_api_dict()` → `_sanitize_metadata()` 用于 API 响应

## 适用调用点和边界

| 调用点 | 模式 | 函数链 | 输出特征 |
|--------|------|--------|----------|
| `POST /processing-profiles` (create audit) | redacted | `_write_audit_log → _sanitize_state → redact_state` | `[REDACTED]` + `_redaction` meta |
| `PATCH /processing-profiles/{id}` (update audit) | redacted | 同上 | 同上 |
| `DELETE /processing-profiles/{id}` (delete audit) | redacted | 同上 | 同上 |
| `POST /processing-profiles/rollback` (rollback audit) | redacted | `_write_rollback_audit_log → _sanitize_state → redact_state` | 同上 |
| `POST /processing-profiles/preview-diff` | redacted | `compute_diff → _sanitize_state → redact_state` | `[REDACTED]` in old/new |
| `GET /processing-profiles/audit` | redacted | `list_audit_log` 返回已脱敏 DB 数据 | 已存储的脱敏数据 |
| `GET /processing-profiles` (API list) | removal | `build_api_profile_list → to_api_dict → _sanitize_metadata → remove_metadata` | 敏感 key 消失 |
| `GET /processing-profiles/matrix` | removal | `build_matrix` 使用 `to_api_dict` | 同上 |

## 删除的重复实现

原 `repositories/processing_profile.py` 中的以下私有函数改为 thin wrapper：

- `_is_sensitive_key()` → 委托 `sanitizer.is_sensitive_key`
- `_is_sensitive_value()` → 委托 `sanitizer.is_sensitive_value`
- `_sanitize_metadata_json()` → 委托 `sanitizer.redact_metadata`
- `_sanitize_state()` → 委托 `sanitizer.redact_state`
- `_sanitize_list()` → **删除**（不再需要，redact_metadata 内部处理 list）

原 `processing_profile/models.py` 中的以下私有函数改为 thin wrapper：

- `_is_sensitive_key` → **删除**
- `_is_sensitive_value` → **删除**
- `_sanitize_metadata()` → 委托 `sanitizer.remove_metadata`
- `_sanitize_metadata_list()` → **删除**

## 漂移防护测试

测试文件: `tests/test_processing_profile_sanitizer.py`

### 核心漂移防护测试

1. **`test_drift_all_sensitive_keys_handled_consistently`** — SENSITIVE_KEY_PARTS 中每个词同时在 redact 和 remove 模式下生效
2. **`test_drift_all_sensitive_value_prefixes_handled_consistently`** — SENSITIVE_VALUE_PREFIXES 中每个模式同时在两种模式下生效
3. **`test_drift_detection_classifies_caller_sites`** — 验证 repository wrapper、shared redact、shared remove 三个调用点输出一致
4. **`test_drift_repository_model_api_same_output_for_redacted_keys`** — 给定相同 metadata，repo 被脱敏的 key 在 model API 输出中也不存在
5. **`test_drift_state_sanitizer_agrees_with_metadata_sanitizer`** — `_sanitize_state` 的 `metadata_json` 内容与 `_sanitize_metadata_json` 一致
6. **`test_drift_no_plaintext_secrets_in_output`** — 验证两种模式的输出都不含明文 secret 样例

### 漂移定位失败信息

当漂移发生时，失败信息包含：
- 具体路径（如 `"auth.token"`）
- 模式名称（Redact vs Remove）
- 期望与实际值的对比

示例：
```
AssertionError: Remove mode leaked 'auth.token' (redact mode redacted it)
AssertionError: Path drift: shared=['auth.token'] vs repo_wrapper=['auth.api_key']
```

## 保留值边界

- 非敏感 key 且非敏感值的字段原样保留
- `null`/`None`、空数组 `[]`、空对象 `{}`、布尔值、数值原样保留
- 非 dict 值的 `metadata_json` 不会进入递归（`redact_state` 中只对 dict 类型递归）

## 已知边界 (非当前任务)

- 值级检测仅覆盖 Bearer 前缀和 PEM 头
- 不做语义分析（如 `{"type": "secret", "value": "sk-xxx"}` 中的 `value` 不会被脱敏）
- Python 递归深度无硬上限
- 不迁移历史 audit 数据
- 不做完整 DLP/PII
- 不改 API schema
- 不接 secret 存储

## 验证清单

- [x] `make lint` 通过
- [x] `make test` 通过（含新增 `test_processing_profile_sanitizer.py`）
- [x] `make coverage` 通过
- [x] `make web-check` 通过
- [x] 共享 helper 独立模块 `sanitizer.py`
- [x] repository diff/rollback/audit 与 `to_api_dict()` 均调用同一 helper
- [x] 重复实现已删除或改为 wrapper
- [x] 单测覆盖敏感 key、Bearer/private key 值、嵌套 dict/list、null/scalar/空数组
- [x] redacted 模式输出 `[REDACTED]`，removal 模式不返回敏感字段
- [x] 漂移防护测试覆盖三类调用点
- [x] 测试失败信息能定位调用点
