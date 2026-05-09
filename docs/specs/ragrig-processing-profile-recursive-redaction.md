# RAGRig ProcessingProfile metadata_json 递归脱敏

**版本**: 1.0  
**日期**: 2026-05-09  
**状态**: Implemented  
**Issue**: EVI-71

## 概述

将 ProcessingProfile audit log / diff / rollback preview 中的 metadata_json 脱敏逻辑从仅顶层 key 检查扩展为递归深度遍历，覆盖嵌套对象 (dict) 和数组 (list)，杜绝嵌套 secret 泄露。

## 变更范围

### 1. `src/ragrig/repositories/processing_profile.py`

#### 脱敏规则

| 条件 | 行为 | 示例 |
|------|------|------|
| key 名匹配敏感词 | 值替换为 `[REDACTED]` | `{"api_key": "sk-xxx"}` → `{"api_key": "[REDACTED]"}` |
| 嵌套 dict | 递归进入 | `{"auth": {"token": "xyz"}}` → `{"auth": {"token": "[REDACTED]"}}` |
| 嵌套 list | 遍历每个元素，递归处理 | `{"items": [{"secret": "x"}]}` → `{"items": [{"secret": "[REDACTED]"}]}` |
| 值匹配 Bearer token / PEM | 值替换为 `[REDACTED]` | `{"header": "Bearer abc"}` → `{"header": "[REDACTED]"}` |
| 非敏感 key + 非敏感值 | 原样保留 | `{"version": 2, "tags": ["a"]}` → 不变 |
| null / 空数组 / 空对象 | 原样保留 | `{"empty": [], "nil": null}` → 不变 |
| 非 dict 值的 metadata_json | 原样保留（key 不到 else 分支） | 不会进入递归 |

#### 敏感 key 词表（`SENSITIVE_KEY_PARTS`）

```
api_key, access_key, secret, session_token, token, password,
private_key, credential, dsn, service_account
```

匹配规则：`key.lower()` 包含任一词表项即触发（substring match）。

#### 敏感值模式（`_SENSITIVE_VALUE_PATTERNS`）

- `bearer ` — Bearer token
- `-----begin` — PEM 私钥头

匹配规则：`str(value).lower()` 包含任一模式即触发（substring match, case-insensitive）。

#### 新增函数

- `_is_sensitive_key(key: str) -> bool` — key 名敏感判定
- `_is_sensitive_value(value: object) -> bool` — 标量值敏感判定
- `_sanitize_metadata_json(metadata, prefix) -> (dict, count, paths)` — 递归脱敏，返回三元组
- `_sanitize_list(items, prefix) -> (list, count, paths)` — 数组递归脱敏
- `_compute_changed_paths_recursive(old, new, prefix, changed)` — 递归 diff 路径收集
- `_sanitize_state` 现在会在脱敏后添加 `_redaction` 元数据

#### diff API 输出增强

`compute_diff()` 返回的 dict 现在包含：

- `old` / `new` — 递归脱敏后的完整状态（不含 `_redaction` 内部 key）
- `changed_paths` — 支持嵌套路径（如 `metadata_json.auth.api_key`），按字母序排序
- `redaction_count` (best-effort) — 脱敏字段总数
- `redacted_paths` (best-effort) — 被脱敏的路径列表

#### rollback / audit preview

- `_write_audit_log()` 和 `_write_rollback_audit_log()` 均通过 `_sanitize_state()` 脱敏
- `_sanitize_state()` 自动处理 metadata_json 的递归脱敏
- 回滚后的审计日志也经过相同的递归脱敏

### 2. `src/ragrig/processing_profile/models.py`

`_sanitize_metadata()` 也升级为递归脱敏，确保 API profile list 响应中的嵌套 metadata 不泄露：

- 敏感 key 的条目被移除
- 嵌套 dict/list 被递归处理
- Bearer token / PEM 值被移除

### 3. Diff API 端点不变

`POST /processing-profiles/preview-diff` 的请求/响应格式保持不变，但 `old`/`new` 中的 `metadata_json` 现在是递归脱敏后的结果，且新增 `redaction_count` 和 `redacted_paths` 字段。

### 4. Rollback API 端点不变

`POST /processing-profiles/rollback` 无变更，但审计日志中的 `old_state`/`new_state` 现在是递归脱敏后的结果。

## 保留值边界

以下值不被脱敏，原样保留：

- 不带敏感词的非标量值（如 `{"version": 2}` 中的 `2`）
- 空数组 `[]`、空对象 `{}`
- `null` / `None`
- 布尔值 `true` / `false`
- 非敏感字符串（如 `"hello"`, `"model.ollama"`）
- 非敏感 list 中的非敏感元素

## 已知漏报边界

- **值级检测不全面**：仅对 `bearer ` 前缀和 PEM 头做 pattern match。不以这些前缀开头的 token/secret 字符串（如 `sk-proj-xxx` 作为普通字典值且 key 不匹配敏感词）不会被脱敏。
- **二进制数据**：不会解析 bytes/blob 内容。
- **嵌套深度无上限**：依赖 Python 递归栈，极端深度可能导致 RecursionError（实际场景 unlikely）。
- **不检查语义**：`"hello world"` 中恰好出现 `"bearer"` 子串会被误脱敏。这是已知可接受的误报代价。
- **跨字段关联**：不做跨字段联合分析（如 `{"type": "api_key", "value": "sk-xxx"}` 中 `value` 不会被脱敏）。

这些边界在 DLP/PII 完整实现范围内，不属于当前任务。

## 被排除的边界

不做：
- 完整 DLP/PII 检测
- Secret 存储/加密
- 多租户 RBAC
- 历史 audit 数据迁移
- 真实 LLM execution 中的 secret 处理

## Web Console 影响

Web Console diff 展示面板通过 `/preview-diff` API 获取数据，API 返回的 `old`/`new` 已经是递归脱敏后的结果。Web Console 无需额外修改即可不泄露嵌套 secret。

## 验证要点

1. `make lint` / `make test` / `make coverage` / `make web-check` 全部通过
2. Diff API 对嵌套 dict/list 中的敏感字段返回 `[REDACTED]`
3. old/new/changed_paths 不含明文 secret
4. changed_paths 按字母序排序，稳定可预测
5. Rollback / audit preview 复用同一递归 sanitizer
6. 非敏感嵌套值保持可读
7. null / scalar / 空数组 / 异常 metadata 结果确定可复现
8. 输出 `redaction_count` / `redacted_paths`
