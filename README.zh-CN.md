<p align="center">
  <img src="./assets/ragrig-icon.svg" alt="RAGRig logo" width="160" height="160">
</p>

<h1 align="center">RAGRig 源栈</h1>

<p align="center">
  <strong>面向可追溯、模型可用知识流水线的开源 RAG 工作台。</strong>
</p>

<p align="center">
  <a href="./README.md">English</a>
</p>

---

## 项目定位

RAGRig 是一个面向中小型团队的开源 RAG 工作台。

RAGRig 不是另一个“上传文件然后聊天”的壳子。它关注 RAG 真正难长期维护的工程层：入库、解析、清洗、chunk、embedding、索引、检索、答案引用、模型 Provider、评测和可追溯性。

## 优势特点

- **本地优先：** 默认从本地文件、Postgres/pgvector、Ollama、LM Studio、BGE、自托管 OpenAI-compatible runtime 开始。
- **云端兼容：** 支持 OpenAI、OpenRouter、Gemini 等主流入口，Vertex AI、Bedrock 等先进入模型目录和 roadmap。
- **全链路可追溯：** 答案能回到 source URI、文档版本、chunk、pipeline run 和模型诊断。
- **模型可插拔：** LLM、embedding、reranker、OCR、parser 都走清晰的 Provider Registry。
- **向量库可迁移：** 默认 pgvector，Qdrant 可选。
- **流水线可观察：** 解析、清洗、切分、向量化、索引、重排都能被检查，而不是藏在聊天框后面。
- **插件化扩展：** source、sink、model、vector backend、parser、preview、workflow node 都可通过插件扩展。
- **质量门禁：** 核心模块目标 100% 测试覆盖；云端和企业插件通过 contract test 与显式 live smoke 验证。

## 架构图

```mermaid
flowchart LR
    inputs["输入<br/>文件、URL、对象存储、文档系统、DB"]
    pipeline["流水线<br/>解析、清洗、切分、向量化、索引"]
    core["RAGRig core<br/>知识库、文档、版本、chunk、run、审计"]
    providers["Provider registry<br/>LLM、embedding、reranker、parser"]
    vectors["向量后端<br/>默认 pgvector，可选 Qdrant"]
    console["Web Console<br/>配置、预览、健康检查、Playground"]
    answer["检索 + 答案<br/>命中、引用、诊断"]

    inputs --> pipeline
    providers --> pipeline
    pipeline --> core
    core --> vectors
    vectors --> answer
    core --> console
    providers --> console
    answer --> console
```

## 技术栈

| 层级 | 当前 / 默认 | 可选 / Roadmap |
| --- | --- | --- |
| App/API | Python、FastAPI | MCP / export surface |
| Web Console | FastAPI 内置轻量 Console | 更完整的 workflow UI |
| 元数据数据库 | PostgreSQL | SQLite 用于 smoke/test |
| 向量后端 | pgvector | Qdrant |
| 本地模型 | Ollama、LM Studio、OpenAI-compatible endpoint | vLLM、llama.cpp、Xinference、LocalAI |
| 云端模型 | OpenAI、OpenRouter、Gemini | Vertex AI、Bedrock、Azure OpenAI、Anthropic 等目录项 |
| 输入源 | 本地文件、Markdown/TXT、S3-compatible source | PDF/DOCX 上传、URL、企业连接器 |
| 质量验证 | pytest、coverage、contract tests | 显式 opt-in live provider smoke |

## Roadmap

### Local Pilot

下一阶段 roadmap 里先做简单本地试点。它是平台演进的一环，不是项目定位本身。

目标用户路径：

1. 启动本地栈。
2. 打开 Web Console。
3. 创建知识库。
4. 上传 Markdown、TXT、PDF、DOCX，或导入单网页 URL、sitemap、docs 页面列表。
5. 选择模型 Provider。
6. 运行入库和索引。
7. 在 Playground 提问，并检查答案引用、检索命中、chunk 和模型诊断。

范围和验收条件见 [Local Pilot spec](./docs/specs/ragrig-local-pilot-spec.md)。

### 后续里程碑

- 更完整的 Web Console workflow 管理
- 高级 PDF/DOCX/OCR 解析
- 更丰富的 source 和 sink 插件
- evaluation dashboard 与回归质量门
- 企业权限、审计和连接器加固

### Phase 3 — 中小团队集成（已完成）

P3 阶段交付了中小团队最常需要的集成和管控能力：

- **OpenAI 兼容 API + MCP 服务端 + SSE 流式响应** —— 任何 OpenAI SDK / MCP 客户端都可以指向 `POST /v1/chat/completions`（模型标识 `ragrig/<kb>[@provider:model]`）、`GET /v1/models` 或 `POST /mcp`；REST 回答与 chat completion 均支持 `stream=true`。
- **多轮对话 + 反馈闭环 + 引用高亮** —— `POST /conversations` 自动把历史 turn 折入检索；`POST /conversations/{id}/turns/{turn}/feedback` 记录 👍/👎 及原因；引用现在带 `char_start/char_end/page_number`，前端可直接做段内高亮。
- **用量 / 成本看板 + 预算告警** —— 每次 retrieval/answer 都会落 `usage_event`；`GET /usage` 与 `GET /usage/timeseries` 汇总 token / 费用 / 时延；`PUT /budgets` 设置每工作区月度预算，触发邮件 + webhook 告警（同期内只发一次，可选 hard cap 直接拒绝）。
- **Confluence + Notion + 飞书 / Lark 连接器** —— 可插拔 `HttpTransport` 实现，配置支持 `env:NAME` 解析；`POST /sources/{source}/webhook` 接收上游变更通知，按源密钥做 HMAC-SHA256 验签。
- **管理面板 + 工作区备份/恢复** —— `GET /admin/status` 给出概览统计；`GET /admin/backup/{workspace_id}` 返回独立 JSON dump；`POST /admin/restore` 按 id upsert，可重复执行不会重复写入。

## Web Console

Web Console 是 RAGRig 的主要操作界面。第一版形态：

- 知识库列表
- source 配置与入库任务
- 模型配置和健康检查
- pipeline run 历史
- 文档和 chunk 预览
- 检索与答案 Playground
- 健康检查和数据库/向量状态

原型图：

<p align="center">
  <img src="./docs/prototypes/web-console/ragrig-web-console-prototype.png" alt="RAGRig Web Console 原型图" width="860">
</p>

## 快速部署

### Docker Compose（推荐）

```bash
git clone https://github.com/evilgaoshu/ragrig.git
cd ragrig
docker compose up
```

打开 `http://localhost:8000` 即可。

容器启动时会自动：
- 多阶段构建从源码组装 React 控制台
- 运行 alembic 迁移（`RAGRIG_AUTO_MIGRATE=1`）
- 从 `examples/local-pilot/*.md` 种入 `demo` 知识库，Playground 立刻能提问
- 默认回答 provider 是 `deterministic-local`，无需任何 API key
- demo 模式下 auth 默认关闭；正式对外暴露前在 `.env` 设置
  `RAGRIG_AUTH_ENABLED=true`

`docker compose down` 关闭。可选服务（MinIO/S3、Qdrant、fileshare 实时
smoke）的环境变量见
[docs/operations/optional-services.md](./docs/operations/optional-services.md)。

### Vercel Preview + Supabase

在线产品预览可以用 Vercel Preview + Supabase Postgres。本地体验仍推荐
Docker。必需环境变量：

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/postgres?sslmode=require
VECTOR_BACKEND=pgvector
APP_ENV=preview
```

先在可信本地/CI 环境执行 migration，再做部署 smoke：

```bash
DATABASE_URL='postgresql://USER:PASSWORD@HOST:PORT/postgres?sslmode=require' \
DB_RUNTIME_HOST='HOST' DB_HOST_PORT='PORT' \
uv run alembic upgrade head

VERCEL_PREVIEW_URL='https://your-preview-url.vercel.app' make vercel-preview-smoke
```

模型配置仍然不影响启动，完整契约见
[EVI-130](./docs/specs/EVI-130-vercel-preview-supabase.md)。

### Pilot 脚本

需要带 evidence 的端到端 smoke（preflight + 构建 + 控制台走查）时，原有
target 依然可用：

```bash
make pilot-docker-preflight   # 检查 Docker 可用
make pilot-up                 # docker compose up -d db app
make pilot-docker-smoke       # 输出 JSON evidence
make pilot-down               # 关闭
```

镜像不内置 LLM 权重。要用真实模型，可在宿主机跑 Ollama / LM Studio 并把
`RAGRIG_ANSWER_BASE_URL` 指向它，或在 `.env` 里设置 `OPENAI_API_KEY` /
`OPENROUTER_API_KEY` / `GEMINI_API_KEY`。

只构建应用镜像：

```bash
make pilot-docker-build
```

### 开发环境

安装依赖：

```bash
make sync
```

创建本地环境文件：

```bash
cp .env.example .env
```

启动数据库并执行 migration：

```bash
docker compose up --build -d db
make migrate
make db-check
```

运行当前本地入库和索引 smoke：

```bash
make ingest-local
make index-local
make retrieve-check QUERY="RAGRig Guide"
```

运行 Local Pilot API smoke：

```bash
make local-pilot-smoke
```

启动 Web Console：

```bash
make run-web
```

打开：

```text
http://localhost:8000/console
```

如果宿主机的 `8000` 或 `5432` 已被占用，可以在 `.env` 里改端口：

```bash
APP_HOST_PORT=18000
DB_HOST_PORT=15433
```

可选 Qdrant 路径：

```bash
docker compose --profile qdrant up -d qdrant
uv sync --extra vectorstores
VECTOR_BACKEND=qdrant make index-local
VECTOR_BACKEND=qdrant make retrieve-check QUERY="RAGRig Guide"
```

## 验证

默认检查：

```bash
make format
make lint
make test
make coverage
make web-check
make local-pilot-smoke
make dependency-inventory
```

nightly evidence 路径已接入 GitHub Actions；本地具备 Docker live smoke 条件时可直接运行：

```bash
make nightly-evidence-smoke
```

浏览器级 Local Pilot Console 检查：

```bash
make local-pilot-console-e2e
```

该命令会启动临时 SQLite 应用，验证一次失败上传/重试路径，再通过 Web Console 上传 Markdown/PDF/DOCX，检查 pipeline/chunk UI，并在 Playground 发起一次 grounded answer。它需要 `npm` 和本地 Chrome/Chromium；如果没有 Chrome，可设置 `RAGRIG_CONSOLE_E2E_BROWSER_CHANNEL=chromium`。

供应链检查：

```bash
make licenses
make sbom
make audit
```

`make audit` 需要网络访问漏洞服务。离线环境请改跑 `make audit-dry-run`，并把缺失的 live audit 记录为发布 blocker。

## 认证

RAGRig 内置基于密码的认证系统和 Workspace 级租户隔离。

### 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RAGRIG_AUTH_ENABLED` | `true` | 启用认证。本地开发可设为 `false`（无需登录）。 |
| `RAGRIG_AUTH_SESSION_DAYS` | `30` | Session token 有效天数。 |
| `RAGRIG_AUTH_SECRET_PEPPER` | 内置开发默认值 | 用于 token 哈希的 HMAC pepper。**生产环境必须替换。** |

### 首次启动

启用认证后，访问 Web Console 会跳转至登录页。通过 **创建账号** 注册第一个账号，
该账号自动获得默认 Workspace 的 `owner` 角色。

### 角色权限

| 角色 | 说明 |
| --- | --- |
| `owner` | 完整访问权限，包括成员管理和角色分配 |
| `admin` | 可管理成员（owner 角色除外）及所有写操作 |
| `editor` | 可写入知识库、运行 pipeline、上传文档 |
| `viewer` | 只读访问 |

写入路由（如 `POST /knowledge-bases`、上传文档、pipeline 和 source 操作）需要
`editor` 及以上权限。Processing profile 的变更和回滚需要 `admin` 及以上权限。

### 成员管理

```bash
# 查看 Workspace 成员列表
curl /auth/workspace/members \
  -H "Authorization: Bearer rag_session_..."

# 修改成员角色（需要 admin 或 owner）
curl -X PATCH /auth/workspace/members/{user_id} \
  -H "Authorization: Bearer rag_session_..." \
  -H "Content-Type: application/json" \
  -d '{"role": "editor"}'

# 移除成员（需要 admin 或 owner）
curl -X DELETE /auth/workspace/members/{user_id} \
  -H "Authorization: Bearer rag_session_..."
```

### 关闭认证（本地开发）

```bash
RAGRIG_AUTH_ENABLED=false uv run uvicorn ragrig.main:app --reload
```

所有请求以匿名用户身份路由到默认 Workspace，无需登录。

## 生产防护

RAGRig 默认在生产环境禁用 deterministic fake reranker fallback。只有明确用于
demo 或可接受降级环境时，才设置 `RAGRIG_ALLOW_FAKE_RERANKER=true`。
`/health` 会返回当前 reranker policy。

## 文档

核心文档：

- [Fake reranker 生产防护](./docs/specs/EVI-129-fake-reranker-production-guard.md)
- [Local Pilot spec](./docs/specs/ragrig-local-pilot-spec.md)
- [MVP spec](./docs/specs/ragrig-mvp-spec.md)
- [Web Console spec](./docs/specs/ragrig-web-console-spec.md)
- [插件/数据源向导 spec](./docs/specs/ragrig-web-console-plugin-source-wizard-spec.md)
- [本地优先、质量与供应链策略](./docs/specs/ragrig-local-first-quality-supply-chain-policy.md)
- [核心覆盖率与供应链门禁](./docs/specs/ragrig-core-coverage-supply-chain-gates.md)

运维文档：

- [Dependency inventory](./docs/operations/dependency-inventory.md)
- [Supply chain](./docs/operations/supply-chain.md)
- [Roadmap](./docs/roadmap.md)

## 仓库结构

```text
.
├── assets/             # 项目图标
├── docs/               # 规格、运维文档、原型图
├── scripts/            # smoke、运维、验证命令
├── src/ragrig/         # RAGRig 应用代码
├── tests/              # 单元测试和 contract tests
├── docker-compose.yml  # 本地 Postgres/pgvector 与可选服务
├── pyproject.toml      # Python 依赖和工具配置
└── Makefile            # 常用开发命令
```

## License

RAGRig 使用 Apache License 2.0。详见 [LICENSE](./LICENSE)。
