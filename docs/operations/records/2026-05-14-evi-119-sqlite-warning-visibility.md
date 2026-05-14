# EVI-119 Raw SQLite ResourceWarning Visibility Entry

Date: 2026-05-14
Issue: EVI-119
Related issue: [EVI-118](mention://issue/c63693e4-4f88-4786-ba38-73e45025a21d)
Environment: pytest warning policy and raw sqlite leak visibility recheck

## Goal

Provide a stable, cross-platform verification entry proving the project does not silently suppress raw `sqlite3.connect(...)` leak `ResourceWarning` signals via pytest `filterwarnings` configuration.

## Verification Entry

- Automated regression check: `tests/test_sqlite_warning_visibility.py`
- Stable command entry: `make sqlite-warning-check`
- Underlying implementation: `scripts/sqlite_warning_check.py`

The automated check is configuration-based on purpose. It verifies that `pyproject.toml` does not contain broad sqlite `ResourceWarning` suppression rules, so it remains stable on Linux with Python 3.11 and 3.12 without depending on GC timing.

## CI Scope

- `tests/test_sqlite_warning_visibility.py` runs as part of default pytest suites, so it is covered by `make test` and `make coverage`.
- `make sqlite-warning-check` is a dedicated operator-facing entry for manual or targeted rechecks.
- The raw sqlite leak smoke path is not part of required CI checks because interpreter-specific GC finalization timing can make direct warning emission nondeterministic.

## Runtime Differences

- Python 3.11 and 3.12 can differ in when an unclosed raw `sqlite3.Connection` is finalized.
- Because `ResourceWarning` emission may occur only when the object is garbage-collected, identical leak code can warn in one runtime build and stay silent in another until process teardown.
- The stable guarantee for EVI-119 is therefore `no sqlite warning suppression layer is configured`, not `every runtime emits the warning immediately`.

## Relationship To EVI-118

EVI-118's SQLAlchemy sqlite engine teardown cleanup remains a test-only cleanup safety net. It is not a warning suppression layer:

- it only tracks engines created through `sqlalchemy.create_engine`
- it does not track direct `sqlite3.connect(...)` connections
- it cannot hide raw sqlite leak warnings by filter configuration

## Manual Smoke Recheck

Use this only when you want to observe whether the active interpreter build emits the raw warning signal:

```bash
uv run python -W always::ResourceWarning -c 'import gc, sqlite3, tempfile; db = tempfile.NamedTemporaryFile(suffix=".db", delete=False); conn = sqlite3.connect(db.name); conn.execute("select 1"); del conn; gc.collect()'
```

Expected outcomes:

- if the interpreter emits the warning, it must appear unsuppressed
- if no warning appears, `make sqlite-warning-check` must still report that no sqlite suppression filter is configured

## Failure Triage

If `make sqlite-warning-check` fails:

1. Run `grep -n "ResourceWarning" pyproject.toml` and inspect any pytest `filterwarnings` entries.
2. Remove any sqlite- or `ResourceWarning`-specific ignore rule instead of broadening the check.
3. Re-run `uv run pytest tests/test_sqlite_warning_visibility.py -q`.
4. If a raw warning smoke command behaves differently across Python 3.11 and 3.12, treat that as runtime timing variance unless the stable suppression check also fails.
