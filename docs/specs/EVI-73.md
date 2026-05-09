# SPEC — EVI-73：Understanding Runs 导出文件名摘要与 Schema Fixture v1.0

## 概述

为 Understanding Runs 导出增加可读文件名摘要和可复用 schema fixture，便于人工归档和外部校验。

## 变更范围

### 1. 导出文件名摘要生成 (`build_export_filename`)

- **位置**: `src/ragrig/understanding/service.py`
- 新增 `build_export_filename()` 函数，根据 filter 生成稳定、可读的下载文件名
- 文件名格式: `ragrig-runs-{kb}_{provider}_{model}_{profile}_{status}_{time}_{limit}_{date}.json`
- 仅已设置的 filter 出现在文件名中，未设置项不出现
- 非法文件名字符 (`/\:*?"<>|`) 自动替换为 `_`
- 导出的 `_filename` 字段包含在 export JSON 响应中

### 2. 前端集成

- **位置**: `src/ragrig/web_console.html`
- `exportSingleRun()` 和 `exportFilteredRuns()` 使用响应中的 `_filename` 作为下载文件名
- Copy Link 按钮构建包含 filter 参数的 shareable URL

### 3. Schema Fixture

- **位置**: `tests/fixtures/understanding_export_contract.json`
- 字段覆盖: `schema_version`, `generated_at`, `filter`, `run_count`, `run_ids`, `runs`
- 无 secrets、完整 prompt、完整原文

### 4. Fixture 校验

- **位置**: `scripts/verify_export_fixture.py`
- `make verify-export-fixture` target
- 校验 fixture 字段完整性、无敏感数据泄露

### 5. 测试覆盖

- `TestBuildExportFilename` (11 tests): 文件名生成逻辑
- Web Console tests (4 tests): 导出端点响应中的 `_filename`

## 不变更项

- 不改变 EVI-68 已定义的 export JSON schema 契约（仅增加 `_filename` 字段）
- 不做云端归档、登录态分享、BI 报表

## 验证清单

1. `make lint` — 通过
2. `make test` — 633 passed, 9 skipped
3. `make verify-export-fixture` — PASS
4. `make web-check` — 186 passed
5. `make coverage` — 通过
