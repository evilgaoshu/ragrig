# EVI-110 Pilot Go/No-Go Evidence Pack

Generated: `2026-05-13T04:39:46.199776Z`
Decision evidence status: `evidence_recorded`

## Pilot Source And Corpus

- Source path: `fileshare-live SMB/WebDAV/SFTP`
- Rationale: The pilot uses a live networked document connector with seeded fixtures as the explicit real-source equivalent when Google Workspace credentials are not part of reproducible repo CI.
- Fixed corpus root: `tests/fixtures/fileshare_live`
- Fixed corpus file count: `9`

| Corpus file | Bytes | SHA-256 |
| --- | ---: | --- |
| `tests/fixtures/fileshare_live/samba/binary.bin` | 7 | `268576d50a742ae1cd715dd6a92d811c5b04f1a66a7e13ae15f75f315a3ebe5c` |
| `tests/fixtures/fileshare_live/samba/guide.md` | 31 | `d5303aa2c5018659b3cd6a6710d0913b3376b71b020512ea3ecb89e66b04e7d1` |
| `tests/fixtures/fileshare_live/samba/notes.txt` | 14 | `95844967f0adaab75df6d14fd81068b0193adac1b87c8d78279ffd02ba53fc2e` |
| `tests/fixtures/fileshare_live/sftp/binary.bin` | 7 | `268576d50a742ae1cd715dd6a92d811c5b04f1a66a7e13ae15f75f315a3ebe5c` |
| `tests/fixtures/fileshare_live/sftp/guide.md` | 31 | `d5303aa2c5018659b3cd6a6710d0913b3376b71b020512ea3ecb89e66b04e7d1` |
| `tests/fixtures/fileshare_live/sftp/notes.txt` | 14 | `95844967f0adaab75df6d14fd81068b0193adac1b87c8d78279ffd02ba53fc2e` |
| `tests/fixtures/fileshare_live/webdav/binary.bin` | 7 | `268576d50a742ae1cd715dd6a92d811c5b04f1a66a7e13ae15f75f315a3ebe5c` |
| `tests/fixtures/fileshare_live/webdav/guide.md` | 31 | `d5303aa2c5018659b3cd6a6710d0913b3376b71b020512ea3ecb89e66b04e7d1` |
| `tests/fixtures/fileshare_live/webdav/notes.txt` | 14 | `95844967f0adaab75df6d14fd81068b0193adac1b87c8d78279ffd02ba53fc2e` |

## Golden Questions

| Query | Tags | Expected document |
| --- | --- | --- |
| `retrieval ready guide` | smoke, hit | `guide.md` |
| `ops notes for the console` | smoke, hit | `notes.txt` |
| `deeply nested content` | smoke | `nested/deep.md` |
| `nonexistent query xyzzy` | miss, zero-results | `-` |
| `empty file content` | edge-case | `empty.txt` |
| `binary file content` | edge-case | `binary.bin` |

## Evidence Commands

| Evidence | Command | Primary artifact | Evidence | Observed outcome |
| --- | --- | --- | --- | --- |
| Equivalent real-source connector path | `make test-live-fileshare` | `docs/operations/artifacts/fileshare-live-smoke-record.json` | `recorded` | `blocked` |
| Retrieval and answer quality baseline | `uv run python -m scripts.eval_local --ephemeral-sqlite --output docs/operations/artifacts/pilot-eval-local.json && uv run python -m scripts.retrieval_benchmark_compare --pretty --latency-threshold-pct 500 --output docs/operations/artifacts/pilot-retrieval-benchmark-compare.json` | `docs/operations/artifacts/pilot-eval-local.json` | `recorded` | `completed` |
| Supporting artifact | - | `docs/operations/artifacts/pilot-retrieval-benchmark-compare.json` | - | `pass` |
| Citation, refusal, and degraded answer diagnostics | `make answer-live-smoke` | `docs/operations/artifacts/answer-live-smoke.json` | `recorded` | `skip` |
| Failure inspect, retry, and audit trail | `make pipeline-dag-smoke` | `docs/operations/artifacts/pipeline-dag-smoke.json` | `recorded` | `completed` |
| Backup, restore, and upgrade summary | `make ops-backup-smoke && make ops-restore-smoke && make ops-upgrade-smoke` | `docs/operations/artifacts/ops-backup-summary.json` | `recorded` | `degraded` |
| Supporting artifact | - | `docs/operations/artifacts/ops-restore-summary.json` | - | `failure` |
| Supporting artifact | - | `docs/operations/artifacts/ops-upgrade-summary.json` | - | `failure` |

## Go / No-Go Rules

Go when:
- All five evidence groups are recorded from the documented commands.
- ACL regression and citation/refusal checks remain covered by make test.
- Required repository gates make lint, make test, make coverage, and make web-check pass.

No-go when:
- Live connector evidence is blocked without an accepted equivalent-source record.
- Retrieval comparison reports failure or artifacts are missing.
- Restore/upgrade diagnostics hide failure instead of reporting success/degraded/failure.

## Residual Risk

- Google Workspace remains outside the reproducible repo-local pilot route; the live fileshare connector is the declared equivalent real-source evidence.
- Answer provider smoke may intentionally report degraded or skip where a local LLM is unavailable; that remains decision evidence, not an unreported success.
- Live connector smoke requires Docker and optional fileshare SDKs, so blocked preflight output must be retained as explicit evidence when the lab lacks them.
