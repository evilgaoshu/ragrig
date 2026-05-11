# SPEC — EVI-83：Answer Provider Optional Live Smoke + Prompt Snapshot

## 概述

为 Answer Generation 增加可选本地 LLM live smoke 测试和 prompt/citation snapshot 回归，证明 deterministic provider 之外的本地 runtime 可用且失败可降级。

## 验证方式（hard requirements）

1. `make lint && make test && make coverage && make web-check` 全部通过
2. 本 SPEC 文档说明 Ollama / LM Studio / OpenAI-compatible 本地 provider 配置方式、skip/degraded 语义和 secret 脱敏边界
3. 新增 `make answer-live-smoke` target
4. 新增 snapshot fixture 文件 `tests/fixtures/answer_snapshots/`
5. 新增 pytest marker `answer_live_smoke`
6. 默认 CI（`make test`）不执行 live smoke

---

## 1. 本地 Provider 配置方式

### 1.1 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `RAGRIG_ANSWER_LIVE_SMOKE` | (unset) | 设为 `1` 启用 live smoke |
| `RAGRIG_ANSWER_PROVIDER` | `ollama` | Provider 名称（用于 audit/log） |
| `RAGRIG_ANSWER_MODEL` | `llama3.2:1b` | 模型名称/ID |
| `RAGRIG_ANSWER_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible API base URL |

### 1.2 Ollama 示例

```bash
# 1. Start Ollama
ollama serve

# 2. Pull a small model
ollama pull llama3.2:1b

# 3. Run live smoke
RAGRIG_ANSWER_LIVE_SMOKE=1 make answer-live-smoke
```

Ollama provides an OpenAI-compatible endpoint at `http://localhost:11434/v1`, which is the default `RAGRIG_ANSWER_BASE_URL`.

### 1.3 LM Studio 示例

```bash
# 1. Start LM Studio with local inference server enabled
#    Default port: 1234

# 2. Run live smoke against LM Studio
RAGRIG_ANSWER_LIVE_SMOKE=1 \
  RAGRIG_ANSWER_BASE_URL=http://localhost:1234/v1 \
  RAGRIG_ANSWER_MODEL=local-model \
  make answer-live-smoke
```

### 1.4 任意 OpenAI-compatible 端点

```bash
RAGRIG_ANSWER_LIVE_SMOKE=1 \
  RAGRIG_ANSWER_BASE_URL=https://my-provider.example.com/v1 \
  RAGRIG_ANSWER_MODEL=my-model \
  RAGRIG_ANSWER_PROVIDER=openai-compatible \
  make answer-live-smoke
```

---

## 2. Skip / Degraded 语义

### 2.1 Skip（未配 LLM）

当 `RAGRIG_ANSWER_LIVE_SMOKE` 环境变量**未设置**时（默认行为）：

- 所有标记 `@pytest.mark.answer_live_smoke` 的测试被 **skip**
- skip reason 明确："set RAGRIG_ANSWER_LIVE_SMOKE=1 to run answer live smoke tests"
- 这不是 false success — 这是显式 opt-in gate

### 2.2 Degraded / xfail（provider 不可达）

当 `RAGRIG_ANSWER_LIVE_SMOKE=1` 但 provider 不可达时：

- `test_answer_with_live_provider_returns_grounded_answer` 使用 `pytest.xfail` 标记为 **degraded**（不是 success）
- xfail reason 明确说明 provider 不可达，提示用户启动本地 LLM server
- `test_provider_unreachable_is_xfail` 始终 xfail 当 provider 不可达，作为自文档化检查

### 2.3 Success（正常路径）

`RAGRIG_ANSWER_LIVE_SMOKE=1` 且 provider 可达时：

- 使用 fixture KB（`answer-live-smoke`）进行端到端 answer 生成
- 断言 `grounding_status == "grounded"`
- 断言 `len(citations) >= 1`
- 断言 answer 中包含引用的 citation ID
- 断言 answer 中不含 secret

---

## 3. Secret 脱敏边界

### 3.1 快照 fixture 脱敏

`tests/fixtures/answer_snapshots/` 中的所有文件：

- `prompt_template.txt` — 不含 api_key / token / password / sk-*
- `citation_format.json` — 不含 api_key / token / password / sk-*
- `refusal_boundary.json` — 不含 api_key / token / password / sk-*

**验证方式**：`test_answer_snapshot_fixtures_contain_no_secrets` 扫描所有 snapshot 文件，按规则检查 `api_key`, `token`, `password`, `secret`, `sk-*`, `Bearer *` 模式。

### 3.2 日志脱敏

Live smoke 测试本身不记录 raw provider 响应到日志。任何 provider 错误都走 `_sanitize_error_message()` 管道，该管道：

- 替换 `api_key=*`, `secret=*`, `token=*`, `password=*`
- 替换 `sk-*`（OpenAI key 模式）
- 截断至 500 字符

### 3.3 API 脱敏

Live smoke 测试不启动 HTTP server，仅通过 Python API (`generate_answer()`) 调用，复用现有脱敏逻辑。

---

## 4. Snapshot Fixture 文件

### 4.1 `prompt_template.txt`

固定 system_prompt + user_prompt 模板，与 `LLMAnswerProvider` 中的一致。用于 prompt 未 drift 的回归检测。

### 4.2 `citation_format.json`

定义 evidence 块格式样例：
- `citation_id` 模式：`cit-{N}`（N 为 1-indexed 检索排名）
- 字段结构：`document_uri`, `score`, `text`
- 正则模式：`\[cit-\d+\]`

### 4.3 `refusal_boundary.json`

定义无 evidence 时的拒答文本：
- Deterministic provider: `"I cannot answer this question because no relevant evidence was found in the knowledge base."`
- LLM provider: 同上（复用 Deterministic 的早期返回路径）

### 4.4 回归测试

- `test_prompt_template_matches_snapshot_fixture` — 断言 `LLMAnswerProvider` 的 system prompt 关键短语仍出现在 fixture 中
- `test_deterministic_answer_matches_refusal_fixture` — 断言 `DeterministicAnswerProvider` 的无 evidence 输出与 fixture 完全匹配
- `test_citation_format_matches_fixture` — 断言 citation regex 有效、字段名与 schema 一致
- `test_answer_snapshot_fixtures_contain_no_secrets` — 扫描所有 snapshot 确认不含 secret

---

## 5. Pytest Marker

`answer_live_smoke` 已注册在 `pyproject.toml` 的 `[tool.pytest.ini_options.markers]` 中：

```toml
"answer_live_smoke: live smoke tests for answer generation with local LLM (requires RAGRIG_ANSWER_LIVE_SMOKE=1)",
```

---

## 6. Make Target

```makefile
answer-live-smoke:
    $(UV) run pytest -m answer_live_smoke
```

执行方式：

```bash
# 不设置环境变量 → 所有 tests skip
make answer-live-smoke

# 设置环境变量 → 实际执行 live smoke
RAGRIG_ANSWER_LIVE_SMOKE=1 make answer-live-smoke
```

---

## 7. 不变更项

- 不接云端 required smoke
- 不做多轮对话 / LLM judge / 生产压测
- 不在日志/API/snapshot 暴露 secret
- 不修改现有 CI gate 依赖（`make test` 不包含 `answer_live_smoke`）
