# SPEC — EVI-95: Sanitizer Contract Matrix Artifact 与 Console Badge

**Version:** 1.0
**Date:** 2026-05-12
**Status:** Approved
**Scope:** `scripts/sanitizer_contract_check.py` callsite matrix artifact + Web Console badge

---

## 1. Goal

让 sanitizer contract checker 输出可审阅的 callsite matrix，并在 Console/CI artifact 中展示最新合同状态。

---

## 2. Artifact Schema

### 2.1 文件路径

| Format | Path |
|--------|------|
| JSON | `docs/operations/artifacts/sanitizer-contract-matrix.json` |
| Markdown | `docs/operations/artifacts/sanitizer-contract-matrix.md` |
| 生成命令 | `make sanitizer-contract-check` |

### 2.2 JSON Schema

```json
{
  "artifact": "sanitizer-contract-matrix",
  "version": "1.0.0",
  "generated_at": "2026-05-12T00:00:00+00:00",
  "status": "pass",
  "exit_code": 0,
  "totals": {
    "callsites": 10,
    "registered": 8,
    "unregistered": 0,
    "summary_fields_ok": true,
    "no_duplicate_impls": true,
    "fixture_ok": true
  },
  "matrix": [
    {
      "callsite": "ragrig.repositories.processing_profile:_sanitize_metadata_json",
      "layer": "ragrig",
      "registered": true,
      "summary_fields_ok": true,
      "status": "pass",
      "reason": ""
    }
  ]
}
```

### 2.3 Matrix 字段

| Field | Type | Description |
|-------|------|-------------|
| `callsite` | `string` | `module:function` 格式的完整调用点 |
| `layer` | `string` | 模块顶层包名（如 `ragrig`） |
| `registered` | `boolean` | 是否在 `REGISTERED_CALL_SITES` 中注册 |
| `summary_fields_ok` | `boolean` | `SanitizationSummary` 字段是否完整 |
| `status` | `string` | `pass` / `failure` / `unregistered` |
| `reason` | `string` | 失败原因（空字符串表示通过） |

### 2.4 Artifact 状态

| 状态 | 含义 |
|------|------|
| `pass` | 所有合同检查通过，exit_code == 0 |
| `degraded` | 部分 check 失败但未阻断（exit_code == 0 + 部分 matrix failure） |
| `failure` | 合同检查失败，exit_code != 0 |

---

## 3. Console Badge

### 3.1 API 端点

`GET /sanitizer-contract-status` — 返回轻量摘要，专供 Web Console 渲染。

### 3.2 返回字段

| Field | Type | Description |
|-------|------|-------------|
| `available` | `boolean` | artifact 是否存在且可读 |
| `status` | `string` | `pass` / `degraded` / `failure` |
| `exit_code` | `int` | 原始 exit code |
| `registered_callsite_count` | `int` | 已注册的 callsite 数量 |
| `report_path` | `string` | artifact 相对路径 |
| `generated_at` | `string` | ISO 8601 时间戳 |
| `unregistered_count` | `int` | 未注册的 callsite 数量 |
| `summary_fields_ok` | `boolean` | summary 字段检查是否通过 |
| `no_duplicate_impls` | `boolean` | 重复实现检查是否通过 |
| `fixture_ok` | `boolean` | fixture smoke 是否通过 |

### 3.3 UI 展示

- **Status strip card**: 显示最新 status、registered count、unregistered count
- **Panel**: 展示 status pill、registered count、unregistered count、summary_fields_ok、no_duplicate_impls、fixture_ok、generated_at、report_path

**缺失/损坏 artifact 处理**：
- artifact 不存在 → `status: failure`, `reason: "artifact not found"`
- artifact 损坏（JSON decode error） → `status: failure`, `reason: "corrupt artifact: ..."`
- artifact schema 不兼容 → `status: failure`, `reason: "invalid artifact type"`
- 以上情况均以 red pill 展示 failure，不误报 pass

---

## 4. 脱敏边界

1. Artifact 中绝不包含原始 secret 值
2. 输出前执行 `_assert_no_raw_secrets` 强制安全检查，匹配以下 forbidden fragments：
   - `sk-live-`, `sk-proj-`, `sk-ant-`
   - `ghp_`
   - `Bearer `
   - `PRIVATE KEY-----`
   - `super_secret_db_pass`, `db-super-secret-999`, `prod-api-secret-key-2024`
3. Console API 返回的数据经过 `_assert_console_no_secrets` 审计
4. 如果 artifact 包含 secret-like 内容导致审计失败，检查器停止写入并报告错误

---

## 5. 验证命令

```bash
# Lint
make lint

# All tests
make test

# Coverage
make coverage

# Web console check
make web-check

# Sanitizer contract check (generates matrix artifact)
make sanitizer-contract-check

# 单独运行 contract matrix 测试
cd tests && uv run pytest test_sanitizer_contract_matrix.py -v
```

## 6. 测试覆盖

| 测试 | 覆盖场景 |
|------|---------|
| `test_contract_matrix_artifact_created` | matrix artifact 正确创建并包含所有必填字段 |
| `test_contract_matrix_has_expected_structure` | matrix 每行包含 callsite/layer/registered/summary_fields_ok/status/reason |
| `test_contract_matrix_status_pass` | 全部通过时 status=pass、exit_code=0 |
| `test_contract_matrix_status_failure_on_unregistered` | 含未注册 callsite 时 status=failure |
| `test_console_badge_missing_artifact` | artifact 不存在时返回 failure |
| `test_console_badge_corrupt_artifact` | artifact 损坏时返回 failure |
| `test_console_badge_secret_leak_blocked` | artifact 含 secret 片段被拦截 |

---

## 7. 不做边界

- 不新增 DLP/PII 规则
- 不改 summary v1 schema（schema_version 保持 "1.0"）
- 不接外部观测平台
- 不做长期趋势存储

---

## 8. Change Log

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-05-12 | Initial spec. Implemented callsite matrix artifact (JSON+MD), console badge, unit tests. |
