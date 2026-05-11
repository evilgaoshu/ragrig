# SPEC: Sanitizer Degraded Summary 与调用点观测

**Schema Version**: 1.0  
**Issue**: EVI-87  
**Status**: Implemented

---

## 1. 目标

让 `processing_profile/sanitizer.py` 的 redact/remove/depth-limit 降级结果以结构化 summary 返回给调用点，消除静默处理。

---

## 2. Summary Schema

```python
@dataclass(frozen=True)
class SanitizationSummary:
    schema_version: str = "1.0"
    redacted_count: int = 0
    removed_count: int = 0
    degraded_count: int = 0
    non_string_key_count: int = 0
    max_depth_exceeded: bool = False
```

| 字段 | 含义 |
|------|------|
| `schema_version` | 版本标识，初始 `"1.0"` |
| `redacted_count` | 显式 redact 的敏感键/值数量（含 `[REDACTED]` 替换） |
| `removed_count` | 显式 remove 的敏感键/值数量（remove 模式） |
| `degraded_count` | depth-limit 触发次数 |
| `non_string_key_count` | 遍历过程中遇到的非字符串 key 数量 |
| `max_depth_exceeded` | 是否曾触发深度截断 |

### 2.1 安全约束

- summary **不输出**完整 secret、完整原文、大字段值、不可序列化 key 的原始 repr
- 仅输出计数和布尔标志，路径信息仍通过原有 `redacted_paths` 返回（redact 模式）

---

## 3. 调用点传播

### 3.1 `redact_metadata()`

```python
def redact_metadata(...) -> tuple[dict, int, list[str], SanitizationSummary]:
    ...
```

- 返回值增加第 4 个元素 `SanitizationSummary`
- 第 2 个元素 `count` 保持向后兼容，语义为 `redacted_count`（含 DEGRADED 触发的 redaction）

### 3.2 `remove_metadata()`

```python
def remove_metadata(...) -> tuple[dict, SanitizationSummary]:
    ...
```

- 返回值从单个 dict 变为 `(dict, SanitizationSummary)` 元组

### 3.3 `redact_state()`

```python
def redact_state(...) -> dict[str, Any]:
    ...
```

- 返回 dict **始终**包含 `_sanitization_summary` 键（即使无 redaction）
- 当有 redaction 时，仍保留原有 `_redaction` 键

### 3.4 Repository 层

`repositories/processing_profile.py`:

- `_sanitize_metadata_json()` 返回 `tuple[dict, int, list[str], SanitizationSummary]`
- `_sanitize_state()` 透传 `redact_state()` 的结果（含 `_sanitization_summary`）

### 3.5 Model 层

`processing_profile/models.py`:

- `_sanitize_metadata()` 返回 `tuple[dict, SanitizationSummary]`
- `to_api_dict()` 在 metadata 存在 sanitization 事件时，在返回 dict 的顶层附加 `_sanitization_summary`
- **兼容边界**：clean metadata（全零 summary）不附加该键，避免 API 误报

### 3.6 API 端点

`main.py` 的 processing-profile 相关端点使用 `to_api_dict()` 构建响应：

- 正常 metadata 不新增误报（`_sanitization_summary` 仅在有事件时出现）
- 异常深度输入不抛 `RecursionError`（`DEFAULT_MAX_DEPTH=100` 保护不变，summary 路径不破坏）

---

## 4. 路径脱敏

- `redacted_paths` 继续返回 dot-separated 路径（如 `metadata_json.auth.token`）
- 非字符串 key 在路径中以 `str(key)` 表示（如 `level1.42.api_key`）
- summary 中仅计数，不输出 key 的原始 repr

---

## 5. 兼容边界

| 边界 | 行为 |
|------|------|
| 空 metadata | summary 全零，redact_state 仍包含 `_sanitization_summary` |
| 非字符串 key | 计数到 `non_string_key_count`，值继续正常遍历 |
| 深度截断 | `degraded_count++`, `max_depth_exceeded=True` |
| secret-like 值 | 按 `is_sensitive_value()` 规则处理，计数到 `redacted_count`/`removed_count` |
| 多调用点 | `_sanitize_metadata_json()`、`remove_metadata()`、`_sanitize_metadata()` 对同一输入产生一致的计数 |
| API 响应 | clean metadata 不附加 `_sanitization_summary` |

---

## 6. 单测覆盖

新增/更新的测试覆盖以下场景：

1. **no-op**（空 metadata）— 验证 summary 全零
2. **非字符串 key** — 验证 `non_string_key_count` 正确
3. **深度截断** — 验证 `degraded_count>0` 和 `max_depth_exceeded=True`
4. **secret-like 样例** — 验证 `redacted_count`/`removed_count` 正确
5. **多调用点 summary 一致性** — 验证 repository/model/sanitizer 对同一输入计数一致
6. **summary 不泄露 secret** — 验证 `summary.to_dict()` 字符串表示不含原始 secret

---

## 7. 不做边界

- 不做完整 DLP/PII 检测
- 不迁移历史数据
- 不接外部观测平台
- 不运行真实 LLM 调用

---

## 8. best-effort（未实现）

- Web Console 显示 sanitized/degraded badge
- 导出本地 JSON audit artifact

以上两项为 best-effort，本 PR 未包含。
