<p align="center">
  <img src="./assets/ragrig-icon.svg" alt="RAGRig logo" width="160" height="160">
</p>

<h1 align="center">RAGRig 源栈</h1>

<p align="center">
  <strong>面向中小型团队的开源 RAG 工作台 —— 分钟级自部署，流水线可追溯，模型可插拔。</strong>
</p>

<p align="center">
  <a href="./README.md">English</a> ·
  <a href="#本地试用">立刻体验</a> ·
  <a href="#开箱即用的能力">能力</a> ·
  <a href="#ragrig-的差异化定位">对比</a> ·
  <a href="#部署方式">部署</a>
</p>

<p align="center">
  <a href="https://demo.ragrig.dev/"><strong>在线试用</strong></a><br>
  只读 demo：<code>demo@ragrig.dev</code> / <code>ragrig-demo-readonly</code>
</p>

---

RAGRig 服务于 **2–50 人规模的团队**：想自己跑一套带检索的知识层，而不是按
人头买 SaaS 聊天机器人。每个 chunk、每次命中、每次模型调用都看得见摸得着——
不是"上传文件然后聊天"的黑盒。

## 前置条件

Docker 快速试用需要：

- Docker Engine / Docker Desktop 24+，并启用 Compose v2。
- Docker 可用内存至少 4 GB，并预留数 GB 磁盘给镜像层。
- 宿主机 `8000` 端口可用；如已占用，可在 `.env` 设置 `APP_HOST_PORT=18000`。

如果要在 Docker 外做本地开发，请先安装 `uv`：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# 或：brew install uv
```

只改前端时还需要 Node.js 22+ 和 npm。

## 选择路径

| 目标 | 命令 | 说明 |
| --- | --- | --- |
| 本地快速试用 | `make init && docker compose up` | 生成 `.env`，启动 Postgres + 应用，并预置 demo 数据 |
| 先检查本机环境 | `make doctor` | 直接用 `python3`，检查 Docker、`uv`、Node.js、端口和内存 |
| 后端开发 | `make sync && docker compose up -d db && make run-web` | 使用 `uv` 和本地 Postgres 容器 |
| 前端开发 | `cd frontend && npm ci && npm run dev` | 先让后端跑在 `localhost:8000` |
| 生产部署评审 | 阅读[上线前的配置清单](#上线前的配置清单) | 认证、密钥、预算、备份和连接器都要确认 |

## 本地试用

首次 Docker 构建会编译 React 控制台（`npm ci` + Vite build），并同步
Python 依赖。冷启动通常需要约 3-8 分钟；之后会复用 Docker layer，速度会快很多。

```bash
git clone https://github.com/evilgaoshu/ragrig.git
cd ragrig
make init
docker compose up
```

打开 <http://localhost:8000>，进入 Web Console，会看到已经预置的 `demo`
知识库（内容来自 `examples/local-pilot/`）。无需注册、无需 API key、无需
上传，立刻可以提问。

- 镜像多阶段构建，直接把 React 控制台从源码组装进去
- 启动时自动跑 alembic 迁移
- 默认回答 provider 是 `deterministic-local`，不需要任何 LLM 凭据
- `make init` 会生成带本地随机 `RAGRIG_POSTGRES_PASSWORD` 的 `.env`；
  如果缺少该密码，Compose 仍会拒绝启动
- demo 模式下 auth **默认关闭**，对外暴露前在 `.env` 设置
  `RAGRIG_AUTH_ENABLED=true`

`docker compose down` 关闭。

需要更完整的逐步说明和开发路径，请看
[docs/getting-started.md](./docs/getting-started.md)。

## 开箱即用的能力

### 入库与检索
- 默认支持本地文件、Markdown / TXT、S3-compatible 对象存储、PDF / DOCX（文本层）
- 可选 `doc-parsers-advanced`，配合 `advanced_parser=auto` 或 `docling`，提供
  Docling 版面 / 表格感知解析和扫描 PDF 的本地 OCR fallback；OCR 还需要系统
  Tesseract。Docling / MinerU 也可以走轻量 HTTP service mode，不增加默认依赖
- 解析 → 清洗 → 切分 → 向量化 → 索引 → 可选 KG 抽取 → 检索 → 重排，每一步都能在
  pipeline、audit 和 retrieval trace 里检查
- KB 级 [stage-specific model policy](docs/specs/stage-model-policy.md) 可以为
  understand、extract、query、rerank、answer、judge 选择不同 provider / model，并保留
  旧 role routing 的兼容优先级
- Postgres-first Graph-RAG 暴露实体命中、关系证据、source-backed relation path、
  feedback suppression 和 graph rank movement；默认 deterministic 抽取器适合 CI/local，
  可选 provider-backed extractor 支持别名、类型谓词、严格来源校验和可审计 fallback
- 模板化可解释 chunking 支持 recursive 边界和轻量 token-aware 策略，记录 split reason、
  source range，并支持带审计的手动 split / merge override 和显式 reindex
- 默认 pgvector，Qdrant 可选（检索契约一致）
- BGE / Ollama / LM Studio / OpenAI-compatible embedder 与 OpenAI /
  OpenRouter / Gemini 并列可选

### 对外集成
- **OpenAI 兼容 API** —— `POST /v1/chat/completions`、`GET /v1/models`。
  任何 OpenAI SDK 都可以接入，模型标识用
  `ragrig/<kb>[@provider:model]`
- **MCP 服务端** —— `POST /mcp`，把知识库以 MCP tool/resource 形式暴露给
  Claude Desktop、IDE agent 等
- **Webhook 接入** —— Confluence / Notion / 飞书（Lark）连接器，
  `POST /sources/{source}/webhook` 做 HMAC-SHA256 验签
- **流式响应** —— REST 回答与 chat completion 都支持 `stream=true`（SSE）

### 运营管控
- **多轮对话**：自动把历史 turn 折入检索，turn 级 👍/👎 反馈
- **用量看板**：token / 费用 / 时延汇总（`GET /usage`、
  `GET /usage/timeseries`）；`PUT /budgets` 设每工作区月度预算，触发
  email + webhook 告警，可选 hard cap 直接拒绝
- **工作区备份 / 恢复**：`GET /admin/backup/{workspace_id}` 输出独立 JSON
  dump；`POST /admin/restore` 按 id upsert，可重复执行
- **认证 / RBAC**：密码 + API key + session，RBAC（owner/admin/editor/viewer），
  工作区级隔离；可选 LDAP / OIDC / MFA
- **生产防护**：production 默认禁用 fake reranker fallback，`/health`
  返回当前策略
- **可观测性**：Prometheus `/metrics`、OpenTelemetry tracing、结构化 JSON 日志

### 能力启用矩阵

| 能力 | 默认安装 | 可选 extra | 外部服务 | 凭据 |
| --- | --- | --- | --- | --- |
| Docker demo KB 和 deterministic answer | 是 | 无 | Compose 内 Postgres | 不需要 |
| Markdown/TXT/文本层 PDF/DOCX 解析 | 是 | 无 | 不需要 | 不需要 |
| 扫描件 / 版面感知 PDF 解析 | 否 | `doc-parsers-advanced` | 可选 Docling/MinerU HTTP service；本地 OCR 需要 Tesseract | 不需要 |
| pgvector 检索 | 是 | 无 | Postgres/pgvector | 不需要 |
| Qdrant 检索 | 否 | `vectorstores` | Qdrant sidecar 或服务 | 可选 |
| Graph-RAG deterministic 抽取 | 是 | 无 | 不需要图数据库 | 不需要 |
| provider-backed Graph-RAG 抽取 | adapter 默认在 | 按 provider 需要安装 | 所选 LLM endpoint | 托管 provider 需要 |
| RAGAS 指标 | 否 | `eval-ragas` | 通常需要 judge/provider 栈 | 取决于 judge/provider |
| Langfuse tracing | 否 | `observability-langfuse` | Langfuse host | public + secret key |
| Discord/Slack/GitHub source connector | connector 代码默认在 | Discord/Slack REST 复用 `httpx` | 对应厂商 API | bot/app token |
| 本地 ML embedding/rerank | 否 | `local-ml` | 可选 Ollama/LM Studio | 本地端点不需要 |

## RAGRig 的差异化定位

| | RAGRig | LangChain / LlamaIndex | Dify / FastGPT | RAGFlow |
| --- | --- | --- | --- | --- |
| 形态 | 可运行产品 | 代码 SDK | 低代码搭建平台 | RAG 专属产品 |
| 流水线步骤可检查 | 一等公民 | 自行实现 | 部分（隐在节点里） | 一等公民 |
| 答案 → chunk → 文档版本 → run 全链路追溯 | 内置 | 自建 | 部分 | 内置 |
| OpenAI 兼容 API + MCP | 两者都内置 | 无 | OpenAI 兼容 | 部分 |
| 多租户工作区 + RBAC | 内置 | 无 | 内置 | 内置 |
| 默认向量后端 | pgvector（用你的 Postgres） | 无 | 视部署 | ElasticSearch |
| License | Apache 2.0 | MIT / Apache | Apache 2.0（含 notice） | Apache 2.0 |

一句话：**框架给你砖头，搭建平台给你黑盒，RAGRig 给你一条可以交给团队的
可观察流水线。**

## 适合谁 / 不适合谁

**适合：**
- 2–50 人团队搭建自己的内部 handbook / 文档 / 客服知识层
- 已有产品 / Agent / IDE 需要把私有知识接进来，走 OpenAI 兼容 API 或 MCP
- 在乎"模型为什么这么说"的自部署用户——能点开引用，从 chunk 一路看到文档版本和 pipeline run

**不太合适：**
- 个人偶尔用一下 chat-with-pdf —— 桌面工具更轻
- 上亿文档级的企业索引 —— pgvector 是默认，你会先撞到向量库瓶颈
- 想做带分支 LLM 逻辑的可视化 workflow —— 那是 Dify 的强项

## 部署方式

### Docker Compose（推荐）

上面本地试用里的 `docker compose up` 就是支持路径。会拉起 Postgres +
pgvector + 应用，执行 migration，并预置 demo 知识库。Postgres 默认只在
Compose 网络内可达；本地管理可用
`docker compose exec db psql -U ragrig -d ragrig`。

**8000 端口被占用** 时，在 `.env` 设 `APP_HOST_PORT=18000`。

**本地工具确实需要宿主机 DB 端口** 时，显式启用 override：
`docker compose -f docker-compose.yml -f docker-compose.db-port.yml up`。该
override 默认只绑定到 `127.0.0.1`。

**可选 sidecar**（MinIO/S3、Qdrant、Samba/WebDAV/SFTP fileshare smoke、
本地 LLM answer smoke）的环境变量见
[docs/operations/optional-services.md](./docs/operations/optional-services.md)。

### Vercel Preview + Supabase

需要在线产品预览时，可以用 Vercel Preview + Supabase Postgres。本地体验
仍推荐 Docker。必需环境变量：

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/postgres?sslmode=require
VECTOR_BACKEND=pgvector
APP_ENV=preview
```

先在可信本地 / CI 环境执行 migration，再做部署 smoke：

```bash
DATABASE_URL='postgresql://USER:PASSWORD@HOST:PORT/postgres?sslmode=require' \
DB_RUNTIME_HOST='HOST' DB_HOST_PORT='PORT' \
uv run alembic upgrade head

VERCEL_PREVIEW_URL='https://your-preview-url.vercel.app' make vercel-preview-smoke
```

模型凭据仍然可选 —— no model credentials are required for startup。完整
契约见 [EVI-130](./docs/specs/EVI-130-vercel-preview-supabase.md)。

### 10 分钟本地试点演示

需要带 evidence 的端到端 smoke（preflight + 构建 + 控制台走查）时，原有
target 依然可用：

```bash
make pilot-docker-preflight   # 检查 Docker 可用
make pilot-up                 # docker compose up -d db app
make pilot-docker-smoke       # 输出 JSON evidence
make pilot-down               # 关闭
```

模型配置不影响启动。Demo seed 使用 `deterministic-local` provider，无需
任何外部模型即可回答。示例文档：

- `examples/local-pilot/company-handbook.md`
- `examples/local-pilot/support-faq.md`
- `examples/local-pilot/demo-questions.json`

要用真实模型，可在宿主机跑 Ollama / LM Studio 并把 `RAGRIG_ANSWER_BASE_URL`
指向它，或在 `.env` 里设置 `OPENAI_API_KEY` / `OPENROUTER_API_KEY` /
`GEMINI_API_KEY`。

## 上线前的配置清单

把实例从单机自用切到团队 / 对外可访问之前：

1. **打开认证**：设 `RAGRIG_AUTH_ENABLED=true`，并把
   `RAGRIG_AUTH_SECRET_PEPPER` 换成一段长随机串
2. **保留 fake-reranker 防护**：production 默认禁用 deterministic fake
   reranker fallback。只有明确接受降级的 demo 才设
   `RAGRIG_ALLOW_FAKE_RERANKER=true`
3. **决定连接器**：接 Confluence / Notion / 飞书 webhook 时，为每个 source
   设独立密钥，在 `POST /sources/{source}/webhook` 上做 HMAC-SHA256 验签
4. **设置预算**：`PUT /budgets` 给每个工作区设月度上限，告警走 email +
   你的 webhook
5. **定期备份**：`GET /admin/backup/{workspace_id}` 是独立 JSON dump，
  恢复操作幂等

完整 RBAC / 成员管理 / API key 参考：
[docs/operations/auth.md](./docs/operations/auth.md)。

## Web Console

操作员主界面：知识库、source、pipeline run、文档 / chunk 预览、检索 +
答案 Playground（带引用）、用量看板、对话、admin 状态、备份 / 恢复。

当前生产 console 来自 `/app` 下的 React 应用。下图是早期 prototype
mockup，保留作为规格参考：

<p align="center">
  <img src="./docs/prototypes/web-console/ragrig-web-console-prototype.png" alt="RAGRig Web Console 原型图" width="860">
</p>

## 开发与贡献

执行下面命令前，请先按"前置条件"安装 `uv`。

```bash
make sync                       # 用 uv 安装依赖
make init                       # 生成带随机 DB 密码的本地 .env
docker compose up --build -d db # 只拉起数据库
make migrate
make db-check
make run-web                    # http://localhost:8000/
```

本地最小 smoke 路径：

```bash
make ingest-local
make index-local
make retrieve-check QUERY="RAGRig Guide"
make local-pilot-smoke
```

前端（React + Vite）在 `frontend/`，开发时 `npm run dev`。Vite 构建产物
输出到 `src/ragrig/static/dist`，由 FastAPI 在 `/app` 下提供。

**完整验证命令表**（默认套件、浏览器 e2e、nightly evidence、供应链
audit、live provider smoke）：
[docs/operations/verification.md](./docs/operations/verification.md)。

## 架构图

更完整的系统地图、请求生命周期、术语表和 spec 阅读路径见
[docs/architecture.md](./docs/architecture.md)。

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

| 层级 | 当前 / 默认 | 可选 / Roadmap |
| --- | --- | --- |
| App / API | Python、FastAPI | MCP / export surface |
| Web Console | React (Vite) 由 FastAPI 托管 | 更完整的 workflow UI |
| 元数据数据库 | PostgreSQL | SQLite 用于 smoke/test |
| 向量后端 | pgvector | Qdrant |
| 本地模型 | Ollama、LM Studio、OpenAI-compatible endpoint | vLLM、llama.cpp、Xinference、LocalAI |
| 云端模型 | OpenAI、OpenRouter、Gemini | Vertex AI、Bedrock、Azure OpenAI、Anthropic 等目录项 |
| 输入源 | 本地文件、Markdown/TXT、文本层 PDF/DOCX、S3-compatible source | 扫描件 / 版面感知 PDF 走 `doc-parsers-advanced` 或解析服务；URL、企业连接器 |
| 质量验证 | pytest、coverage、contract tests | 显式 opt-in live provider smoke |

## 文档

- **运维：**
  [认证与 RBAC](./docs/operations/auth.md) ·
  [验证命令](./docs/operations/verification.md) ·
  [可选服务](./docs/operations/optional-services.md) ·
  [supply chain](./docs/operations/supply-chain.md) ·
  [dependency inventory](./docs/operations/dependency-inventory.md)
- **规格：**
  [Local Pilot](./docs/specs/ragrig-local-pilot-spec.md) ·
  [MVP](./docs/specs/ragrig-mvp-spec.md) ·
  [Web Console](./docs/specs/ragrig-web-console-spec.md) ·
  [fake reranker 防护](./docs/specs/EVI-129-fake-reranker-production-guard.md) ·
  [Vercel preview + Supabase](./docs/specs/EVI-130-vercel-preview-supabase.md)
- **开发：** [扩展开发教程](./docs/development/extensions.md)
- **Roadmap：** [docs/roadmap.md](./docs/roadmap.md)

## 仓库结构

```text
.
├── assets/             # 项目图标
├── docs/               # 规格、运维文档、原型图
├── frontend/           # React + Vite Web Console
├── scripts/            # smoke、运维、验证命令
├── src/ragrig/         # RAGRig 应用代码
├── tests/              # 单元测试和 contract tests
├── docker-compose.yml  # 本地 Postgres/pgvector 与可选服务
├── pyproject.toml      # Python 依赖和工具配置
└── Makefile            # 常用开发命令
```

## License

RAGRig 使用 Apache License 2.0。详见 [LICENSE](./LICENSE)。
