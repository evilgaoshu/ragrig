# SPEC — Understanding Export Baseline Diff & Drift 报告

**版本**: 1.0.0  
**创建日期**: 2026-05-11  
**状态**: 已批准  
**关联 Issue**: EVI-85

---

## 1. 目标

让 Understanding Runs 导出结果可与指定 baseline 离线对比，生成不泄密的 drift/delta 报告，用于归档回归和人工审计。

---

## 2. Baseline 标识与路径

- **Baseline 来源**: 任意符合 schema_version 1.0 的 Understanding Runs export JSON 文件。
- **标识方式**: 文件系统路径（绝对或相对）。
- **默认 Baseline**: `tests/fixtures/understanding_export_contract.json`
- **默认 Current**: 与 Baseline 相同（用于自检/无漂移场景）。
- **CI/自动化场景**: 通过 `UNDERSTANDING_DIFF_BASELINE` 和 `UNDERSTANDING_DIFF_CURRENT` 环境变量或 Makefile 参数覆盖。

---

## 3. Diff Schema（输出结构）

Diff 报告为 JSON 对象，顶层字段如下：

| 字段 | 类型 | 说明 |
|------|------|------|
| `artifact` | string | 固定值 `"understanding-export-diff"` |
| `version` | string | SPEC 版本，当前 `"1.0.0"` |
| `generated_at` | string | ISO-8601 生成时间 |
| `schema_version` | string | Current export 的 schema_version |
| `schema_compatible` | boolean | Baseline 与 Current schema_version 是否一致 |
| `baseline` | object | `{ run_count, schema_version }` |
| `current` | object | `{ run_count, schema_version }` |
| `runs` | object | `{ added: [id...], removed: [id...], changed: [id...] }` |
| `run_details` | object | 详细的 added/removed/changed 记录（切片字段，无完整文本） |
| `status` | string | `"pass"` / `"degraded"` / `"failure"` |
| `drift_reasons` | array | 每项包含 `type` 与相关元数据 |
| `sanitized_field_count` | int | 输出扫描中检测到的敏感字段数（应为 0） |

### 3.1 Run Detail 切片字段

对于每个 run，diff 仅输出以下字段的对比，绝不包含完整 prompt、原文、error_summary 内容：

- `provider`, `model`, `profile_id`, `trigger_source`, `operator`, `status`
- `total`, `created`, `skipped`, `failed`
- `error_summary_present` (boolean，仅表示有无)
- `started_at`, `finished_at`

---

## 4. Drift 判定

### 4.1 Status 分级

| Status | 条件 | 退出码 |
|--------|------|--------|
| `pass` | 无 schema 不兼容，无 run 增删改 | `0` |
| `degraded` | run 有增、删或字段变化 | `2` |
| `failure` | baseline 缺失、损坏、schema 不兼容，或验证失败 | `1` |

### 4.2 Drift Reason 类型

- `schema_incompatible`: baseline 与 current schema_version 不一致
- `runs_added`: current 中存在 baseline 中不存在的 run
- `runs_removed`: baseline 中存在 current 中不存在的 run
- `run_changed`: 同一 run id 的切片字段发生变化

---

## 5. 脱敏边界

### 5.1 输入验证

Diff 工具在加载 baseline 和 current 时，复用 `scripts.verify_understanding_export` 的验证逻辑：

- 禁止出现 `FORBIDDEN_KEYS`（如 `prompt`, `extracted_text`, `messages`, `raw_response` 等）
- 禁止出现 `SECRET_PATTERNS`（如 `api_key`, `password`, `sk-` 等）

若输入文件包含上述内容，工具在 diff 前即报错，status = `failure`。

### 5.2 输出审计

- 报告生成后，通过 `_assert_no_raw_secrets` 扫描，若发现 `_FORBIDDEN_FRAGMENTS` 中任意片段，立即 panic（RuntimeError）。
- 通过 `_scan_output_sanitization` 统计输出中残留的敏感字段数量，写入 `sanitized_field_count`。
- `error_summary` 仅输出其 presence（`true`/`false`），绝不输出具体文本。

---

## 6. 错误处理

| 场景 | 行为 |
|------|------|
| Baseline 文件不存在 | status=`failure`, exit=1, 写入 failure report JSON |
| Baseline JSON 损坏 | status=`failure`, exit=1, 写入 failure report JSON |
| Baseline 验证失败（含 secret） | status=`failure`, exit=1, 写入 failure report JSON |
| Current 文件损坏 | status=`failure`, exit=1, 写入 failure report JSON |
| Schema 不兼容 | status=`failure`, exit=1, 正常 diff 其余字段仍执行 |
| 无漂移 | status=`pass`, exit=0 |
| 有漂移 | status=`degraded`, exit=2 |

**原则**: 缺失、损坏或 schema 不兼容的 baseline 必须明确 failure/degraded，不误报 success。

---

## 7. 接口与用法

### 7.1 CLI

```bash
python -m scripts.understanding_export_diff \
    --baseline <path> \
    --current <path> \
    --output <path> \
    [--markdown-output <path>] \
    [--format json|markdown|both] \
    [--stdout]
```

### 7.2 Makefile

```bash
# 使用默认 fixture（无漂移自检）
make understanding-export-diff

# 使用自定义 baseline/current
make understanding-export-diff \
    UNDERSTANDING_DIFF_BASELINE=./baseline.json \
    UNDERSTANDING_DIFF_CURRENT=./current.json
```

---

## 8. 测试覆盖

单测覆盖以下场景（见 `tests/test_understanding_export_diff.py`）：

1. **no-drift pass**: 完全相同的 baseline 与 current → status=`pass`
2. **run added**: current 多一个 run → status=`degraded`
3. **run removed**: baseline 多一个 run → status=`degraded`
4. **关键字段 drift**: status/total/created 等变化 → status=`degraded`
5. **missing baseline**: 文件不存在 → status=`failure`
6. **corrupt baseline**: 非法 JSON → status=`failure`
7. **secret-like 泄漏拦截**: 验证层拒绝含 secret 的输入；输出层 panic 若发现 secret 片段
8. **schema 不兼容**: version 不一致 → status=`failure`
9. **空导出对比**: 两者均为空 → status=`pass`
10. **Markdown 渲染**: 各 status 下 Markdown 结构正确
11. **子进程调用**: `python -m scripts.understanding_export_diff` 正常工作

---

## 9. 不做边界

- **不做** 云端归档/上传
- **不做** BI/长期趋势库
- **不运行** 真实 LLM
- **不改变** export v1 schema（`schema_version` 仍为 `"1.0"`）
- **不做** Web Console drift badge（best-effort，不在本 SPEC 范围内）
- **不做** CI 上传 latest diff artifact（best-effort，不在本 SPEC 范围内）

---

## 10. 变更日志

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0.0 | 2026-05-11 | 初版：baseline diff、drift 报告、脱敏边界、测试覆盖 |
