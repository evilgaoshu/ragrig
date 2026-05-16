# Security Policy

RAGRig handles enterprise knowledge, source credentials, and retrieval permissions. Security-sensitive behavior should be treated as core product behavior.

## Reporting Vulnerabilities

Please use [GitHub private vulnerability reporting](https://github.com/evilgaoshu/ragrig/security/advisories/new) to report security issues confidentially. This keeps exploit details out of public issues while giving maintainers the context needed to triage and respond.

If you are unsure whether something qualifies, open a minimal public issue saying you have a security report — maintainers will follow up with a private channel.

Do not post exploitable payloads, credentials, or proof-of-concept code in public issues.

## Security Priorities

- connector credential handling
- API keys and model provider secrets
- tenant, workspace, and knowledge-base isolation
- pre-retrieval permission filtering
- source document access control
- audit logging for ingestion, indexing, retrieval, export, and deletion
- safe handling of untrusted documents and parser outputs

## Supported Versions

RAGRig does not have a stable release yet. Security fixes target the `main` branch.
