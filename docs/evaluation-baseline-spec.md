# Evaluation Baseline 管理与 Run Retention SPEC

版本: 1.0.0  
适用范围: RAGRig Golden Question Evaluation  

---

## 1. 目标

为 Golden Question Evaluation 增加 baseline 固化、选择对比和本地 run 报告保留/清理能力，消除对临时目录和人工约定的依赖。

---

## 2. Baseline 标识与路径

### 2.1 Baseline ID
- 格式: `baseline-<8位hex>` 或自定义字符串
- 由 `promote_run_to_baseline()` 生成或用户指定
- 在 `baseline_registry.json` 中唯一

### 2.2 Baseline 目录结构
```
evaluation_baselines/
  baseline_registry.json      # 注册表: 元数据、current_baseline_id
  <baseline-id>.json          # 固化后的 baseline 报告 (脱敏后)
```

### 2.3 Run 存储目录结构
```
evaluation_runs/
  <run-id>.json               # 单次 evaluation run 报告
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
3. 写入 `baseline_registry.json`，记录:
   - `id`, `created_at`, `promoted_at`, `source_run_id`
   - `promoted_by` (默认 `$USER`)
   - `golden_set_name`, `knowledge_base`, `metrics` 快照
   - `path` (相对路径)
4. 更新 `current_baseline_id`

### 3.2 更新 Baseline
更新即重新 Promote：用新的 run-id 覆盖同名 baseline-id，或生成新的 baseline-id 后手动切换 current。

---

## 4. Retention 策略

### 4.1 清理命令
```bash
make eval-cleanup KEEP_COUNT=20
make eval-cleanup KEEP_DAYS=30
make eval-cleanup KEEP_COUNT=20 KEEP_DAYS=30 DRY_RUN=1
```

### 4.2 保护规则
- **绝不删除**任何被 baseline 引用的 source_run_id 对应的 run
- **绝不删除** current baseline 对应的文件
- 保护优先级: baseline 关联 > keep_count > keep_days

### 4.3 清理逻辑
1. 按 mtime 降序列出 `evaluation_runs/*.json`
2. 受保护的 run 跳过
3. 超出 `keep_count` 且超过 `keep_days` 的 run 删除
4. 支持 `--dry-run` 预览

---

## 5. 脱敏边界

### 5.1 不进入报告的内容
- `api_key`, `access_key`, `secret`, `password`, `token`, `credential`, `private_key`
- 任何长度 >20 且包含上述关键词的字符串值
- 包含 `://` 或 `=` 且含敏感词的 URL/连接串

### 5.2 已脱敏的字段在 baseline 中保持脱敏
Baseline 文件由已脱敏的 run JSON 复制而来，因此不会引入新的 secret。

---

## 6. CLI 接口

| 命令 | 作用 |
|------|------|
| `make eval-local [BASELINE=<id>]` | 运行 evaluation，可选与 baseline 对比 |
| `make eval-baseline RUN_ID=<id>` | 将 run 固化为 baseline |
| `make eval-cleanup KEEP_COUNT=N` | 按数量清理旧 run |

### 6.1 eval-local 的 baseline 解析
`--baseline` 参数支持:
1. 直接文件路径 (存在即使用)
2. Baseline ID (查询 `baseline_registry.json`)
3. `evaluation_baselines/<id>.json` 回退查找

缺失/损坏时:
- 报告输出 `baseline_status: {error, status: "degraded", reason}`
- metrics 中 delta 全为 `null`
- 进程退出码 `2` (degraded)

---

## 7. Web Console 扩展 (best-effort)

- Baseline selector: 在 Evaluation panel 列出可用 baseline
- Delta badge: 对比 current run vs baseline 的 hit@k/MRR 变化
- 最近 run 保留状态: 显示 protected / deleted 标记

---

## 8. CI Artifact (best-effort)

CI coverage job 可附加上传最新 evaluation report artifact，不阻塞主流程。

---

## 9. 不做边界

- 不做 required CI gate (不阻塞 merge)
- 不接云存储 / BI 系统
- 不做 LLM-as-judge
- 不做生产监控告警
- 不存储 raw secret 或完整私有 prompt
