# Contributing to RAGRig

Thanks for your interest in RAGRig.

RAGRig is early, so the most valuable contributions are clear problem reports, connector requirements, deployment constraints, and focused patches that make the first vertical slice stronger.

## Contribution Areas

- document parsers and source connectors
- Qdrant and pgvector indexing behavior
- retrieval, reranking, and citation quality
- permission-aware retrieval and metadata filtering
- local model support
- documentation, examples, and deployment notes

## Development Principles

- Keep the core small and observable.
- Preserve source provenance through every pipeline step.
- Prefer explicit capability matrices over leaky lowest-common-denominator abstractions.
- Treat permissions as retrieval constraints, not post-processing cleanup.
- Add tests for behavior that affects indexing, retrieval, permissions, or source traceability.

## Pull Requests

Before opening a pull request:

1. Keep the change focused.
2. Update docs when behavior changes.
3. Add or update tests when the change touches core behavior.
4. Explain how you verified the change.

## License

By contributing, you agree that your contribution will be licensed under the Apache License 2.0.
