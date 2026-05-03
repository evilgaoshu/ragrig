<p align="center">
  <img src="./assets/ragrig-icon.svg" alt="RAGRig logo" width="160" height="160">
</p>

<h1 align="center">RAGRig</h1>

<p align="center">
  <strong>Open-source RAG governance and pipeline platform for enterprise knowledge.</strong>
</p>

<p align="center">
  <em>源栈: from scattered enterprise sources to traceable, permission-aware, model-ready knowledge.</em>
</p>

---

## About

RAGRig is an open-source platform for building lightweight, governable RAG systems for small and medium-sized teams.

It helps organizations connect scattered knowledge sources, clean and structure documents with LLM-assisted pipelines, index them into vector stores such as Qdrant and pgvector, and serve retrieval results through traceable, permission-aware APIs.

RAGRig is not meant to be another generic chatbot wrapper. Its focus is the hard operational layer around RAG:

- source connectors for documents, wikis, shared drives, databases, object storage, and enterprise document hubs
- customizable ingestion and cleaning workflows
- model registry for LLMs, embedding models, rerankers, OCR, and parsers
- Qdrant and Postgres/pgvector as first-class vector backends
- document, chunk, and metadata versioning
- permission-aware retrieval with pre-retrieval access filtering
- RAG evaluation, observability, and regression checks
- source traceability from answer to document, version, chunk, and pipeline run
- Markdown and document preview/editing integrations for knowledge review workflows

The goal is to make enterprise knowledge usable by AI systems without losing control over source provenance, permissions, quality, or deployment cost.

## Why RAGRig

Many RAG tools make it easy to upload files and chat with them. Production RAG inside a company needs more than that.

Teams need to know where each answer came from, whether the source is still valid, which model created the embedding, who is allowed to retrieve the content, and whether a pipeline change made retrieval better or worse.

RAGRig treats RAG as an operational system:

- **Source-first:** every generated answer should point back to inspectable source material.
- **Governed by default:** access control, metadata, versions, and audit events are part of the core model.
- **Model-flexible:** bring local or hosted LLMs, embedding models, rerankers, OCR, and parsers.
- **Vector-store portable:** start with pgvector, scale to Qdrant, and keep migration paths explicit.
- **Ops-friendly:** designed for Docker Compose first, with a path to Kubernetes later.

## Project Status

RAGRig is in early project design and scaffolding. The initial implementation will focus on a small but complete vertical slice:

1. file and folder ingestion
2. LLM-assisted document cleaning
3. chunking, embedding, and indexing
4. Qdrant and pgvector backends
5. retrieval API with source citations
6. basic pipeline run history and evaluation hooks

## Planned Integrations

Input sources:

- local files and folders
- SMB/NFS
- S3-compatible storage, including Cloudflare R2
- Cloudflare D1, KV, and other platform data sources
- Google Docs / Google Drive
- wiki systems such as Confluence or MediaWiki
- databases
- WPS document middle platform
- OnlyOffice-compatible document services

Output targets:

- Qdrant
- Postgres/pgvector
- S3-compatible storage
- NFS
- relational databases
- Markdown, JSONL, and Parquet exports

Model providers:

- OpenAI-compatible APIs
- Ollama
- llama.cpp
- vLLM
- local embedding and reranker models such as BAAI BGE

## Repository Layout

```text
.
├── assets/
│   ├── ragrig-icon.png
│   └── ragrig-icon.svg
├── docs/
│   └── roadmap.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
└── SECURITY.md
```

## License

RAGRig is licensed under the Apache License 2.0. See [LICENSE](./LICENSE).
