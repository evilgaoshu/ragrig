# RAGRig Local Pilot Company Handbook

RAGRig Local Pilot is a small, local-first demonstration of a traceable RAG workflow.
The demo starts with local Markdown files, creates a knowledge base, indexes chunks,
and answers questions with citation evidence.

The Local Pilot is designed to show the full pipeline run rather than hide ingestion
behind a chat box. A successful run should make document upload, parsing, chunking,
embedding, indexing, retrieval, answer grounding, and citations visible in the Web
Console.

For local models, the preferred first provider is Ollama or LM Studio through an
OpenAI-compatible endpoint. Cloud providers such as Gemini, OpenAI, and OpenRouter
are optional for the demo and should not block the application from starting.

The product promise for the demo is simple: a small team can upload documents,
inspect chunks, ask grounded questions, and verify citations before trusting the
answer.
