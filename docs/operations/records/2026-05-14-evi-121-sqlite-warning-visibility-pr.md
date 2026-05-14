# SQLite Warning Visibility Check — PR Discoverability

Date: 2026-05-14
Issue: [EVI-121](mention://issue/6cd2ea93-c454-4494-99dc-3959cc92c742)

## Changes

1. **GitHub Actions workflow** — New `.github/workflows/sqlite-warning-check.yml` (non-required, PR-triggered + manual dispatch) runs `make sqlite-warning-check` only — no `-W always::ResourceWarning` or raw sqlite GC smoke commands.
2. **Job summary** — Workflow writes a step summary to the PR page directly showing check output.
3. **Docs** — This record documents trigger conditions, commands, expected output, and failure troubleshooting.

## Trigger Conditions

- **Automatic**: Runs on `pull_request` targeting `main`
- **Manual**: Can be triggered via GitHub UI: Actions → SQLite Warning Check → "Run workflow"
- Not required for merge; not part of required CI checks.

## Command

```bash
make sqlite-warning-check
```

Equivalent to:
```bash
uv run python -m scripts.sqlite_warning_check
```

## Expected Output (pass)

```json
{
  "filterwarnings": [],
  "has_sqlite_resourcewarning_suppression": false,
  "status": "ok"
}
```

Exit code 0.

## Failure Output

```json
{
  "filterwarnings": [
    "ignore:unclosed database in <sqlite3.Connection object:ResourceWarning"
  ],
  "has_sqlite_resourcewarning_suppression": true,
  "status": "failure"
}
```

Exit code 1.

## Failure Troubleshooting

1. Check `pyproject.toml` `[tool.pytest.ini_options]` for any `filterwarnings` entry containing `ignore`, `sqlite`, `sqlite3`, or `ResourceWarning`.
2. Remove any entry of the form `ignore:...ResourceWarning...` — these suppress legitimate sqlite connection leak warnings.
3. `always::ResourceWarning` and `error::ResourceWarning` are NOT suppressions and are correctly ignored by the check.
4. Re-run `make sqlite-warning-check` to verify the fix.

## CI Note

This check is intentionally **not** part of the required CI matrix (`ci.yml`). The `ci.yml` workflow explicitly does **not** contain `make sqlite-warning-check` or `-W always::ResourceWarning`, as verified by `tests/test_github_ci_docs.py`.

## Verification

```bash
python scripts/sqlite_warning_check.py
# → {"filterwarnings": [], "has_sqlite_resourcewarning_suppression": false, "status": "ok"}
```
