# SPEC — EVI-75：Answer Generation API 与 Citation Grounding v1.0

## 概述

在现有 retrieval + ACL filtering + provider registry 基础上，新增第一版可验收的 grounded answer generation 能力：输入问题，先检索授权 chunks，再通过本地优先 LLM 生成带引用的答案；无证据时明确拒答，不伪造来源。

## 变更范围

### 1. Answer 模块 (`src/ragrig/answer/`)

#### 1.1 Schema (`schema.py`)

| 类型 | 用途 |
|---|---|
| `Citation` | 引用元数据：`citation_id`, `document_uri`, `chunk_id`, `chunk_index`, `text_preview`, `score`, `metadata_summary`（仅安全字段） |
| `EvidenceChunk` | 证据块：`citation_id`, `document_uri`, `chunk_id`, `chunk_index`, `text`, `score`, `distance` |
| `AnswerReport` | 结构化响应：`answer`, `citations`, `evidence_chunks`, `model`, `provider`, `retrieval_trace`, `grounding_status`, `refusal_reason` |
| `GroundingStatus` | `"grounded"` \| `"refused"` \| `"degraded"` \| `"error"` |
| `NoEvidenceError` | 无检索结果 → 拒答（code: `no_evidence`） |
| `ProviderUnavailableError` | 答案 provider 不可用（code: `provider_unavailable`） |

#### 1.2 Provider (`provider.py`)

- **`DeterministicAnswerProvider`**：CI/testing 专用，不依赖网络/LLM/secret。输入 query + evidence chunks → 输出带 citation ID 引用的模板式答案。无 evidence 时返回明确拒答。
- **`LLMAnswerProvider`**：封装 ProviderRegistry 中任意 chat/generate 能力的 provider。chat() 失败时 fallback 到 generate()。通过正则 `\[cit-\d+\]` 提取答案中的 citation ID。
- **`get_answer_provider(name, model)`**：工厂函数。`"deterministic-local"` 返回确定性 provider；其他 name 通过 ProviderRegistry 解析并包装为 LLMAnswerProvider。无 chat/generate 能力的 provider 抛出 `ProviderError`。

#### 1.3 Service (`service.py`)

- **`generate_answer()`**：核心 pipeline
  1. 调用现有 `search_knowledge_base()`（ACL-aware）
  2. 无检索结果 → 抛出 `NoEvidenceError`
  3. 构建 `EvidenceChunk` 列表，每个 chunk 有稳定 `cit-N` ID（N 从 1 开始）
  4. 调用 `get_answer_provider().generate(query, evidence)`
  5. Provider 异常 → 经过 `_sanitize_error_message()` 脱敏后抛出 `ProviderUnavailableError`
  6. 验证 provider 返回的 citation ID 与 evidence 中的 citation ID 一致
  7. 返回 `AnswerReport`（grounding_status = grounded | degraded）

### 2. API 端点

**`POST /retrieval/answer`**

| 请求字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `knowledge_base` | string | ✅ | — | KB 名称 |
| `query` | string | ✅ | — | 用户问题 |
| `top_k` | int | ❌ | 5 | 1–50 |
| `provider` | string | ❌ | `"deterministic-local"` | 答案 provider |
| `model` | string | ❌ | null | Provider model ID |
| `dimensions` | int | ❌ | null | >0 |
| `principal_ids` | string[] | ❌ | null | ACL 主体列表 |
| `enforce_acl` | bool | ❌ | true | 是否执行 ACL 过滤 |

错误响应：
- 404: `KnowledgeBaseNotFoundError`
- 400: `EmptyQueryError`, `InvalidTopKError`, `EmbeddingProfileMismatchError`
- 503: `AnswerProviderUnavailableError`

无证据→拒答（仍返回 200，`grounding_status: "refused"`）。

### 3. ProcessingProfile 扩展

- **新 TaskType**: `ANSWER = "answer"`
- **默认 Profile**: `*.answer.default` → `deterministic-local`, `DETERMINISTIC`, tags: `["default", "wildcard", "citation-required"]`
- `get_matrix_task_types()` 包含 `TaskType.ANSWER`

### 4. Web Console 面板

- 新增 "Answer Generation" 面板（位于 "Retrieval Lab" 之后）
- 四种状态：
  - **disabled**：无 KB 时输入/按钮均禁用，显示提示
  - **ready**：有 KB 时启用，显示 provider 元信息
  - **error**：API 错误时显示脱敏错误信息
  - **empty/refused**：无证据时显示拒答原因
- `renderAnswerControls()`, `runAnswer()`, `renderAnswerResult()` 函数

## Prompt 边界（Citation Grounding 语义）

### 确定性 Provider Prompt 结构

```
You are a precise, evidence-grounded answer engine.
Answer ONLY using the provided evidence.
Reference sources using their citation IDs in square brackets, e.g. [cit-1].
If the evidence is insufficient, state clearly that you cannot answer.
Never fabricate information or use knowledge outside the provided evidence.

Question: {query}

Evidence:
[cit-1] (source: {document_uri}, relevance: {score:.2f}):
{chunk_text}
[cit-2] ...

Provide a grounded answer using the evidence above. Always cite sources with their citation IDs.
```

### 引用语义

- 每个 evidence chunk 分配稳定 `cit-N` ID（N 从 1 开始，按检索排名递增）
- Provider 必须在答案中使用 `[cit-N]` 标记引用
- 答案生成后验证：
  - 引用的 `cit-N` 必须存在于 evidence 中
  - 引用了不存在的 citation ID → `grounding_status: "degraded"`
  - 无任何 citation → `grounding_status: "degraded"`，reason 为 "Answer contains no citations"
- Evidence 和 Citation 对象暴露的 metadata 仅包含安全字段；不暴露完整 ACL 列表

### 拒答策略

| 条件 | grounding_status | refusal_reason |
|---|---|---|
| 检索返回 0 结果 | `refused` | `No evidence found in '{kb}' for query: {query}` |
| Provider 抛出异常 | `error`（503 HTTP） | 脱敏后的错误信息 |
| Provider 引用不存在 citation | `degraded` | `Answer references non-existent citations: cit-99, cit-100` |
| Provider 无任何 citation | `degraded` | `Answer contains no citations — grounding cannot be verified.` |

### ACL 与 Secret 安全约束

1. **ACL**：Answer pipeline 完全复用 `search_knowledge_base()` 的 ACL filtering，`principal_ids` + `enforce_acl` 参数透传。protected chunks 不进入 prompt。
2. **Secret 脱敏**：
   - `_sanitize_error_message()` 自动 redact 以下模式：
     - `api_key=*`, `secret=*`, `token=*`, `password=*`
     - `sk-*`（OpenAI key 模式）
   - 截断至 500 字符
   - Citation metadata 仅暴露安全字段（`document_uri`, `chunk_id`, `chunk_index`, `score`, `text_preview`）
   - 不暴露 ACL 详细列表、raw prompt、secret-like metadata
3. **API 响应**：`AnswerReport` 的 `retrieval_trace` 仅包含统计信息（不包含完整 chunk text）

## 不变更项

- 不实现多轮对话记忆
- 不做 agent/tool calling
- 不强制接云端 LLM live smoke
- 不绕过 ACL
- 不做复杂 hallucination scoring（第一版仅 deterministic groundedness/refusal contract）

## 验证清单

1. `make lint` — 通过
2. `make test` — 657 passed, 9 skipped
3. `make coverage` — answer module 100%, overall 99.24% ≥ 90% gate
4. `make web-check` — 86 passed（含 answer panel ready/disabled/error/empty 状态）
5. 单测覆盖：
   - 有证据生成答案 `test_generate_answer_with_evidence_returns_grounded_report`
   - 无证据拒答 `test_generate_answer_no_evidence_raises_no_evidence_error`
   - provider unavailable `test_generate_answer_provider_unavailable`
   - ACL protected 不进入 prompt `test_protected_evidence_not_in_answer_prompt`
   - citation id 一致性 `test_citation_ids_match_evidence_chunks`
   - provider error 脱敏 `test_answer_api_sanitizes_provider_error`
6. 默认测试不依赖网络、真实 LLM、云 secret 或本机 Ollama
