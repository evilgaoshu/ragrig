# SPEC: Answer Live Smoke 本地 Provider 诊断产品化

> 版本：1.0  
> 对应 Issue：[EVI-89](mention://issue/7dc66ee6-5f39-4e53-b85f-f95e48f0feba)

## 目标

为 `make answer-live-smoke` 添加 JSON 诊断报告，让开发者一条命令判断本地 LLM provider（Ollama / LM Studio / OpenAI-compatible）是否可用，失败原因可解释、不产生 import crash 或 false success。

## 安装方式

```bash
# uv
uv sync --extra local-ml

# pip
pip install .[local-ml]
```

`local-ml` extra 包含 `openai`、`ollama`、`torch`、`sentence-transformers`、`FlagEmbedding` 等可选依赖。若未安装，`make answer-live-smoke` 会输出 `skip` 状态并提示安装命令，**绝不会**因 `ImportError` 而崩溃。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RAGRIG_ANSWER_LIVE_SMOKE` | *(未设置)* | 设置为 `1` 时运行端到端 live smoke 测试 |
| `RAGRIG_ANSWER_PROVIDER` | `ollama` | Provider 名称（ollama / lm_studio / llama_cpp / vllm / xinference / localai） |
| `RAGRIG_ANSWER_MODEL` | `llama3.2:1b` | 模型名称 |
| `RAGRIG_ANSWER_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible 端点地址 |

## 使用方式

```bash
# 运行诊断（JSON 输出到 stdout）
make answer-live-smoke

# 手动运行并保存到文件
uv run python -m scripts.answer_live_smoke --output answer-smoke.json

# 指定 provider
uv run python -m scripts.answer_live_smoke --provider lm_studio --base-url http://localhost:1234/v1
```

## 诊断报告 JSON 结构

```json
{
  "base_url_redacted": "http://localhost:11434/v1",
  "citation_count": 2,
  "details": {"reachable": true, "chat_smoke": "Chat smoke completed; response length=42 chars."},
  "model": "llama3.2:1b",
  "provider": "ollama",
  "reason": "Provider healthy. Chat smoke completed; response length=42 chars.",
  "status": "healthy",
  "timing_ms": 1234.56
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `provider` | string | 使用的 provider 名称 |
| `model` | string | 使用的模型名称 |
| `base_url_redacted` | string | 已脱敏的 base URL（不含 API key、token 等） |
| `status` | string | `healthy` / `degraded` / `skip` / `error` |
| `reason` | string | 人类可读的状态说明 |
| `citation_count` | int | smoke chat 返回的 citation 数量 |
| `timing_ms` | float | 总耗时（毫秒） |
| `details` | object | 扩展诊断信息 |

## skip / degraded / error 机制

| 场景 | status | reason 示例 |
|------|--------|-------------|
| 缺少 `openai` 等可选依赖 | `skip` | `Missing optional dependency: openai. Install with: uv sync --extra local-ml` |
| Provider 无法连接（超时/拒绝） | `error` | `Provider unreachable: ConnectionError: ...` |
| Provider 可达但回答不含 citation | `degraded` | `Provider reachable but no citations in response.` |
| Provider 可达且含 citation | `healthy` | `Provider healthy. Chat smoke completed; ...` |

## Secret 边界

- `base_url_redacted` 使用 `_redact_base_url()` 处理：
  - 移除 URL userinfo（如 `http://key@host/` 中的 `key`）
  - 将 query 参数中 key 包含 `api_key` / `secret` / `token` / `password` 的值替换为 `[REDACTED]`
- 脚本输出的 `_sanitize_result()` 会对整个 dict 再做一层 key-based 脱敏
- **绝不**在 JSON 或日志中暴露 raw API key

## 快速开始

### Ollama

```bash
# 1. 安装 Ollama: https://ollama.com
# 2. 拉取模型
ollama pull llama3.2:1b
# 3. 运行诊断
make answer-live-smoke
```

### LM Studio

```bash
# 1. 安装 LM Studio: https://lmstudio.ai
# 2. 加载模型并启动 Local Inference Server
# 3. 设置环境变量并运行
RAGRIG_ANSWER_PROVIDER=lm_studio \
RAGRIG_ANSWER_BASE_URL=http://localhost:1234/v1 \
make answer-live-smoke
```

## 常见错误排查

| 现象 | 可能原因 | 解决方式 |
|------|---------|---------|
| `status: skip`, `missing dependency: openai` | 未安装 `local-ml` extra | `uv sync --extra local-ml` |
| `status: error`, `Connection refused` | Provider 未启动或端口不对 | 确认 Ollama/LM Studio 已运行，检查 `RAGRIG_ANSWER_BASE_URL` |
| `status: degraded`, `no citations` | 模型未按指令输出 citation | 更换模型或检查 prompt 兼容性 |
| 测试被 skip（pytest） | 未设置 `RAGRIG_ANSWER_LIVE_SMOKE=1` | `export RAGRIG_ANSWER_LIVE_SMOKE=1` |

## CI 行为

- 默认 CI（`make test` / `make test-fast`）**不**依赖网络、真实 LLM、cloud secret 或本机 Ollama
- 诊断逻辑的单测使用 mock 注入（`_deps_fn`、`_ping_fn`、`_chat_fn`）覆盖 skip / error / healthy / degraded 路径
- 端到端 live 测试保留在 `TestAnswerLiveSmoke` 中，仍通过 `RAGRIG_ANSWER_LIVE_SMOKE=1` 控制

## 不做边界

- 不做 cloud required smoke（本地 provider 为主）
- 不做 LLM judge / 多轮对话
- 不接生产监控（无 metrics exporter）
- 不暴露 raw secret（已在 redaction 层处理）
