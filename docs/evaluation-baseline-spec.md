# Evaluation Baseline 管理与 Run Retention SPEC

版本: 2.0.0  
适用范围: RAGRig Golden Question Evaluation  

---

## 1. 目标

为 Golden Question Evaluation 增加 baseline 固化、选择对比和本地 run 报告保留/清理能力，消除对临时目录和人工约定的依赖。

**P2 新增**: 引入可验证的 integrity manifest，确保损坏、错版本或错 run 类型的 baseline 在 CLI/API/Console 中一致 degraded/failure。

---

## 2. Baseline 标识与路径

### 2.1 Baseline ID
- 格式: `baseline-<8位hex>` 或自定义字符串
- 由 `promote_run_to_baseline()` 生成或用户指定
- 在 `baseline_registry.json` 中唯一

### 2.2 Baseline 目录结构
```
evaluation_baselines/
  baseline_registry.json          # 注册表: 元数据、current_baseline_id
  <baseline-id>.json              # 固化后的 baseline 报告 (脱敏后)
  <baseline-id>.manifest.json     # 完整性清单 (manifest)
```

### 2.3 Run 存储目录结构
```
evaluation_runs/
  <run-id>.json                   # 单次 evaluation run 报告
```

---

## 3. Promote / Update 流程

### 3.1 固化 Baseline (Promote)
```bash
make eval-baseline RUN_ID=<uuid> [BASELINE_ID=<id>]
# 等价于
uv run python -m scripts.eval_baseline --run-id <uuid> [--baseline-id <id>]
```

流程:
1. 从 `evaluation_runs/<run-id>.json` 加载 run
2. 复制到 `evaluation_baselines/<baseline-id>.json`
3. **写入 `<baseline-id>.manifest.json` (integrity manifest)**，包含:
   - `schema_version`: manifest schema 版本 (当前 `"1.0.0"`)
   - `baseline_id`: baseline 标识
   - `source_run_id`: 来源 run ID
   - `report_path`: baseline 文件路径
   - `metrics_hash`: metrics 的 SHA-256 校验和
   - `created_at`: baseline 创建时间
   - `compatible_eval_schema`: 兼容的 evaluation schema 版本
4. 写入 `baseline_registry.json`，记录:
   - `id`, `created_at`, `promoted_at`, `source_run_id`
   - `promoted_by` (默认 `$USER`)
   - `golden_set_name`, `knowledge_base`, `metrics` 快照
   - `path` (相对路径)
   - `manifest` (清单内容快照)
5. 更新 `current_baseline_id`

### 3.2 更新 Baseline
更新即重新 Promote：用新的 run-id 覆盖同名 baseline-id，或生成新的 baseline-id 后手动切换 current。

---

## 4. Integrity Manifest 与校验

### 4.1 Manifest Schema
```json
{
  "schema_version": "1.0.0",
  "baseline_id": "<id>",
  "source_run_id": "<run-id>",
  "report_path": "evaluation_baselines/<id>.json",
  "metrics_hash": "sha256:<hex>",
  "created_at": "2026-05-11T00:00:00+00:00",
  "compatible_eval_schema": "1.0.0"
}
```

### 4.2 metrics_hash 计算
- 取 baseline JSON 中 `metrics` 对象
- 按 key 排序后序列化为紧凑 JSON (` separators=(",", ":") `)
- SHA-256 摘要，前缀 `sha256:`

### 4.3 校验规则
`load_baseline_metrics_strict()` / `validate_baseline_manifest()` 执行以下校验:
1. **manifest 存在**: 缺失时若 `auto_backfill=True` 自动从 baseline 文件生成；否则报错
2. **manifest 可读**: JSON 损坏 → `corrupt_manifest`
3. **schema_version 兼容**: 不等于 `"1.0.0"` → `incompatible_schema`
4. **metrics_hash 匹配**: baseline 文件 metrics 与 manifest 记录不一致 → `hash_mismatch`
5. **metrics 结构合法**: 缺失或非 dict → `corrupt_manifest`

### 4.4 Legacy Baseline 兼容
- 无 manifest 的旧 baseline 在首次加载时自动 backfill
- backfill 优先使用传入的 `baseline_id` / `source_run_id` / `created_at`
- 未传入时从 baseline 文件内容推断 (`id` → source_run_id, stem → baseline_id)
- 无法推断 `created_at` 时报错

---

## 5. Retention 策略

### 5.1 清理命令
```bash
make eval-cleanup KEEP_COUNT=20
make eval-cleanup KEEP_DAYS=30
make eval-cleanup KEEP_COUNT=20 KEEP_DAYS=30 DRY_RUN=1
```

### 5.2 保护规则
- **绝不删除**任何被 baseline 引用的 source_run_id 对应的 run
- **绝不删除** current baseline 对应的文件
- 保护优先级: baseline 关联 > keep_count > keep_days

### 5.3 清理逻辑
1. 按 mtime 降序列出 `evaluation_runs/*.json`
2. 受保护的 run 跳过
3. 超出 `keep_count` 且超过 `keep_days` 的 run 删除
4. 支持 `--dry-run` 预览

---

## 6. 脱敏边界

### 6.1 不进入报告的内容
- `api_key`, `access_key`, `secret`, `password`, `token`, `credential`, `private_key`
- 任何长度 >20 且包含上述关键词的字符串值
- 包含 `://` 或 `=` 且含敏感词的 URL/连接串

### 6.2 已脱敏的字段在 baseline 中保持脱敏
Baseline 文件由已脱敏的 run JSON 复制而来，因此不会引入新的 secret。

### 6.3 API / Console 不泄漏
- `/evaluations/baselines` 返回的条目已移除 `config_snapshot` 和 `items`
- manifest 本身仅包含 hash，不含原始 metrics 详情

---

## 7. CLI 接口

| 命令 | 作用 |
|------|------|
| `make eval-local [BASELINE=<id>]` | 运行 evaluation，可选与 baseline 对比 |
| `make eval-baseline RUN_ID=<id>` | 将 run 固化为 baseline |
| `make eval-cleanup KEEP_COUNT=N` | 按数量清理旧 run |

### 7.1 eval-local 的 baseline 解析
`--baseline` 参数支持:
1. 直接文件路径 (存在即使用)
2. Baseline ID (查询 `baseline_registry.json`)
3. `evaluation_baselines/<id>.json` 回退查找

缺失/损坏时:
- 报告输出 `baseline_status: {error, status: "degraded", reason}`
- 可能的 `reason` 值:
  - `baseline_missing`: baseline 文件/注册表未找到
  - `missing_manifest`: manifest 文件缺失且无法 backfill
  - `corrupt_manifest`: manifest 或 baseline 文件损坏
  - `hash_mismatch`: metrics 校验和不匹配
  - `incompatible_schema`: manifest schema_version 不兼容
- metrics 中 delta 全为 `null`
- 进程退出码 `2` (degraded)

---

## 8. API / Web Console

### 8.1 `/evaluations/baselines`
返回每个 baseline 的 `integrity_status`:
```json
{
  "status": "valid",
  "schema_version": "1.0.0",
  "metrics_hash": "sha256:...",
  "compatible_eval_schema": "1.0.0",
  "created_at": "..."
}
```
异常状态: `missing_file`, `missing_manifest`, `corrupt`, `hash_mismatch`, `incompatible_schema`

### 8.2 Web Console
- Baseline selector 选项旁显示 integrity status label (`[hash_mismatch]` 等)
- 选中 baseline 后显示 integrity badge:
  - `✓ manifest valid` (绿色)
  - `⚠ <status>: <reason>` (黄色)

---

## 9. CI Artifact (best-effort)

CI coverage job 可附加上传最新 evaluation report artifact，不阻塞主流程。

---

## 10. 不做边界

- 不做 required CI gate (不阻塞 merge)
- 不接云存储 / BI 系统
- 不做加密签名 (仅 SHA-256 checksum)
- 不做生产监控告警
- 不做 LLM-as-judge
- 不存储 raw secret 或完整私有 prompt
