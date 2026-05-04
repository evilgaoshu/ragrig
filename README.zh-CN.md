<p align="center">
  <img src="./assets/ragrig-icon.svg" alt="RAGRig logo" width="160" height="160">
</p>

<h1 align="center">RAGRig 源栈</h1>

<p align="center">
  <strong>面向企业知识的开源 RAG 治理与流水线平台。</strong>
</p>

<p align="center">
  <a href="./README.md">English</a>
</p>

---

## 项目定位

RAGRig 是一个面向中小型团队的轻量化企业知识治理与 RAGOps 平台。

它的目标不是再做一个“上传文件然后聊天”的通用壳子，而是把企业知识从分散来源变成可追溯、可权限控制、可评测、可迁移、可被模型使用的知识资产。

RAGRig 关注的是 RAG 周围真正麻烦的工程层：

- 多来源接入：文件、共享盘、对象存储、Wiki、数据库、企业文档系统。
- 文档解析、清洗、chunk、embedding、indexing 的可配置流水线。
- Qdrant 与 PostgreSQL/pgvector 等向量后端。
- 文档、版本、chunk、embedding、pipeline run 的完整追踪。
- 检索前权限过滤、审计、元数据、版本治理。
- RAG 质量评测、引用准确性、延迟与成本观测。
- Web 管理台用于知识库、数据源、入库任务、文档/chunk、模型和检索调试。

一句话：

```text
RAGRig 把分散企业知识变成可治理、可追溯、模型可用的 RAG 数据底座。
```

## 为什么做 RAGRig

很多 RAG 工具可以很快搭一个问答 demo，但企业落地需要更多东西：

- 这个答案来自哪个源文件、哪个版本、哪个 chunk？
- 源文件是不是过期了？
- 这个用户有没有权限检索这段内容？
- 换了 embedding 模型后，哪些知识库需要重建索引？
- pipeline 变更后，召回质量是变好了还是变差了？
- 数据能不能导出、备份、迁移？
- 本地部署时能不能只用 Postgres/pgvector 跑起来？

RAGRig 把 RAG 当成一个运维系统，而不是聊天界面。

## 当前状态

项目处于早期开发阶段。

当前 main 已经包含：

1. FastAPI 服务骨架与 `GET /health`。
2. Docker Compose 本地开发栈。
3. PostgreSQL + pgvector metadata schema。
4. Alembic migration。
5. 本地 Markdown/Text ingestion。
6. `document_versions`、`pipeline_runs`、`pipeline_run_items` 记录。
7. deterministic local chunking 与 embedding。
8. `chunks` 与 `embeddings` 写入。
9. Web Console 设计文档与静态原型。

还未完成：

- Retrieval API。
- 生产级 embedding provider。
- Qdrant backend。
- 真正可运行的 Web Console。
- ACL enforcement。
- 企业连接器。

权威规格文档：

- [MVP spec](./docs/specs/ragrig-mvp-spec.md)
- [Phase 1a scaffold spec](./docs/specs/ragrig-phase-1a-scaffold-spec.md)
- [Phase 1a metadata DB spec](./docs/specs/ragrig-phase-1a-metadata-db-spec.md)
- [Phase 1b local ingestion spec](./docs/specs/ragrig-phase-1b-local-ingestion-spec.md)
- [Phase 1c chunking and embedding spec](./docs/specs/ragrig-phase-1c-chunking-embedding-spec.md)
- [Web Console spec](./docs/specs/ragrig-web-console-spec.md)
- [Web Console prototype](./docs/prototypes/web-console/index.html)

## 快速开始

安装依赖：

```bash
make sync
```

创建本地环境文件：

```bash
cp .env.example .env
```

如果宿主机的 `8000` 或 `5432` 已被占用，可以在 `.env` 里改端口：

```bash
APP_HOST_PORT=18000
DB_HOST_PORT=15433
```

运行检查：

```bash
make format
make lint
make test
```

启动数据库：

```bash
docker compose up --build -d db
```

执行 migration：

```bash
make migrate
```

检查 pgvector 与 schema：

```bash
make db-check
```

预览本地 fixture 入库，不写数据库：

```bash
make ingest-local-dry-run
```

执行本地 Markdown/Text 入库：

```bash
make ingest-local
```

查看最近 ingestion 结果：

```bash
make ingest-check
```

执行 chunking 和 deterministic local embedding：

```bash
make index-local
```

查看最近 indexing 结果：

```bash
make index-check
```

启动完整本地 API 栈：

```bash
docker compose up --build
```

健康检查：

```bash
curl http://localhost:8000/health
```

如果你改了 `APP_HOST_PORT`，把 URL 里的端口替换成对应值。

## 插件化架构

RAGRig 应该是 plugin-first architecture，但不是第一天就做插件市场。

更稳的路线是：

```text
小内核
  + 稳定插件接口
  + 内置核心插件
  + 官方插件
  + 后续第三方插件生态
```

核心内核负责：

- workspace / knowledge base
- source / document / document_version
- chunk / embedding
- pipeline_run / pipeline_run_item
- metadata / permission boundary / audit event
- plugin registry
- workflow execution

插件负责：

- 输入来源
- 文档解析
- OCR
- 清洗
- chunking
- embedding
- rerank
- vector store
- 输出写入
- 预览与编辑
- 评测
- workflow node

### 插件分类

| 类型 | 作用 | 例子 |
| --- | --- | --- |
| Source connector | 从外部系统读取知识 | local、SMB/NFS、S3/R2、Google Drive、SharePoint、Confluence、数据库 |
| Parser / OCR | 把原始文件转成文本和结构 | Markdown、Text、PDF、DOCX、XLSX、Docling、MinerU、Tesseract、PaddleOCR |
| Cleaner | 规范化、脱敏、分类、去重、补 metadata | deterministic cleaner、LLM cleaner、PII redaction |
| Chunker | 把 document version 切成可追溯 chunk | character window、Markdown heading、recursive chunk、table-aware chunk |
| Model provider | 接入 LLM、embedding、reranker、OCR 模型 | OpenAI-compatible、Ollama、vLLM、llama.cpp、BGE、Jina、Cohere、Voyage |
| Vector backend | 存储和检索向量 | pgvector、Qdrant、Milvus/Zilliz、Weaviate、OpenSearch、Redis/Valkey |
| Output sink | 把治理后的知识或检索产物写出去 | S3/R2/MinIO、NFS、DB、JSONL、Parquet、Markdown、webhook、MCP |
| Preview/Edit | 预览或编辑文档和清洗结果 | Markdown editor、WPS、OnlyOffice、Collabora |
| Evaluation | 评测 RAG 质量 | golden questions、citation coverage、latency/cost、regression checks |
| Workflow node | 拼装 pipeline 步骤 | scan、parse、clean、chunk、embed、index、retrieve、evaluate、export、notify |

### 插件优先级与归属

| 层级 | 含义 | 是否随 core 发布 | 扩展方式 |
| --- | --- | --- | --- |
| 内置核心插件 | 最小可复现 RAG 闭环必需 | 是 | 仓库内维护，无外部服务依赖 |
| 官方插件 | 高频企业集成，由 RAGRig 项目维护 | 可选 | 先放 monorepo，接口稳定后可拆包 |
| 社区插件 | 第三方按公开 contract 实现 | 否 | 后续通过 Python package 或 manifest 安装 |

### 内置核心插件

| 插件 | 类型 | 读写能力 | 为什么内置 |
| --- | --- | --- | --- |
| `source.local` | Source connector | 读 | fresh clone、本地 fixture、共享环境 smoke 的基础 |
| `parser.markdown` | Parser | 读 | 企业文档和开发文档高频格式 |
| `parser.text` | Parser | 读 | 最小文本入库路径 |
| `chunker.character_window` | Chunker | 写 chunk | 可复现、容易测试 |
| `embedding.deterministic_local` | Model provider | 写 embedding | 无 secret、可 CI、可 smoke |
| `vector.pgvector` | Vector backend | 读/写 | 默认轻量后端，Postgres 一套即可跑 |
| `sink.jsonl` | Output sink | 写 | 调试和迁移最方便 |
| `preview.markdown` | Preview/Edit | 读/写草稿 | 清洗结果和 chunk 人工 review 的基础 |

### 官方插件优先级

| 优先级 | 插件方向 | 优先支持平台/协议 |
| --- | --- | --- |
| P0 | `vector.qdrant` | Qdrant Cloud、自托管 Qdrant |
| P0 | `model.openai_compatible` | OpenAI、Azure OpenAI-compatible、vLLM、Ollama、LM Studio、Xinference、llama.cpp server |
| P0 | `embedding.bge` / `reranker.bge` | BAAI BGE embedding 与 reranker，本地或 OpenAI-compatible serving |
| P1 | `source.s3` | AWS S3、Cloudflare R2、MinIO、Ceph RGW、Wasabi、Backblaze B2 S3 API、腾讯 COS S3 API、阿里 OSS S3-compatible 模式 |
| P1 | `sink.object_storage` | AWS S3、Cloudflare R2、MinIO、Ceph RGW、Wasabi、Backblaze B2、Google Cloud Storage、Azure Blob Storage |
| P1 | `source.fileshare` | SMB/CIFS、NFS、WebDAV、SFTP |
| P1 | `source.google_workspace` | Google Drive、Google Docs、Google Sheets、Google Slides |
| P1 | `source.microsoft_365` | SharePoint、OneDrive、Word、Excel、PowerPoint |
| P1 | `source.wiki` | Confluence、MediaWiki、GitBook、Docusaurus、MkDocs |
| P1 | `source.database` | PostgreSQL、MySQL/MariaDB、SQL Server、Oracle、SQLite、MongoDB、Elasticsearch/OpenSearch |
| P1 | `preview.office` | WPS 文档中台、OnlyOffice、Collabora Online |
| P2 | `source.collaboration` | Notion、飞书/Lark Docs、钉钉文档、企业微信文档、Slack files、Teams files |
| P2 | `parser.advanced_documents` | PDF layout、DOCX/PPTX/XLSX、Docling、MinerU、Unstructured |
| P2 | `ocr` | PaddleOCR、Tesseract、云 OCR adapter |
| P2 | `vector.enterprise` | Milvus/Zilliz、Weaviate、OpenSearch/Elasticsearch vector、Redis/Valkey vector、Vespa |
| P2 | `sink.analytics` | Parquet、DuckDB、ClickHouse、BigQuery、Snowflake |
| P2 | `sink.agent_access` | MCP server、webhook、retrieval API export adapter |

### 插件能力声明

每个插件都应该声明：

- plugin id、type、version、owner
- 支持 read/write 哪些操作
- config schema
- secret requirements
- capability matrix
- 是否支持 cursor / incremental sync
- 是否支持 delete detection
- 是否支持 permission mapping
- 失败和重试策略
- metrics 和 audit events

示例：

```yaml
id: ragrig.source.s3
type: source
version: 0.1.0
capabilities:
  read: true
  write: false
  incremental_sync: true
  delete_detection: true
  permission_mapping: false
config_schema: schemas/s3-source.json
secrets:
  - access_key_id
  - secret_access_key
```

## Web Console

Web Console 的第一版目标是轻量管理台，而不是聊天页面。

第一版必须覆盖：

- 知识库列表
- 数据源配置
- 本地文件/Markdown 入库任务
- pipeline run 历史
- 文档/chunk 预览
- 模型配置
- 检索调试 Playground
- 健康检查和数据库状态

设计文档：

- [Web Console spec](./docs/specs/ragrig-web-console-spec.md)
- [Web Console prototype](./docs/prototypes/web-console/index.html)

## 仓库结构

```text
.
├── assets/
│   ├── ragrig-icon.png
│   └── ragrig-icon.svg
├── docs/
│   ├── operations/
│   ├── prototypes/
│   ├── roadmap.md
│   └── specs/
├── scripts/
├── src/ragrig/
├── tests/
├── README.md
├── README.zh-CN.md
└── LICENSE
```

## License

RAGRig 使用 Apache License 2.0。详见 [LICENSE](./LICENSE)。
