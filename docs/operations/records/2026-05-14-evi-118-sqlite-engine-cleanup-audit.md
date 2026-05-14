# EVI-118 SQLite Engine Cleanup Audit Notes

Date: 2026-05-14
Issue: EVI-118
Related issue: [EVI-115](mention://issue/a5188ec1-715e-43fb-aac4-059b6f927e7f)
Environment: pytest sqlite test harness audit

## Goal

Audit the test-only SQLAlchemy sqlite engine cleanup boundary so it stays a teardown safety net, not a new implicit `ResourceWarning` suppression layer.

## Covered Scope

- `tests/conftest.py` patches `sqlalchemy.create_engine` during tests.
- Every SQLAlchemy engine whose backend is `sqlite` is added to `_SQLITE_ENGINES`.
- The autouse fixture `_cleanup_sqlite_engines` runs after each test and calls `_dispose_sqlite_engines()`.
- `_dispose_sqlite_engines()` closes ORM sessions with `close_all_sessions()`, disposes tracked engines, clears the tracking set, and forces `gc.collect()` so teardown failures stay visible during the same test run.

## Non-Covered Scope

- Direct `sqlite3.connect(...)` calls are not tracked.
- Any non-SQLAlchemy resource leak is outside this fixture boundary.
- The fixture is a fallback for tests that forgot to dispose a SQLAlchemy sqlite engine; it is not a license to skip explicit `session.close()` or `engine.dispose()` in helpers that own their lifecycle.

## Failure Signals

- `tests/test_sqlite_engine_cleanup_audit.py::test_dispose_sqlite_engines_cleans_tracked_sqlalchemy_sqlite_engine` proves tracked SQLAlchemy sqlite engines are disposed by the teardown helper.
- `tests/test_sqlite_engine_cleanup_audit.py::test_direct_sqlite3_leak_path_remains_outside_sqlalchemy_cleanup_scope` proves direct `sqlite3.connect(...)` stays outside the SQLAlchemy tracking set, so pytest teardown cannot silently clean it up through `_cleanup_sqlite_engines`.
- `tests/test_github_ci_docs.py::test_pytest_configuration_does_not_reintroduce_sqlite_resourcewarning_filter` guards against reintroducing the removed sqlite `ResourceWarning` warning filter in `pyproject.toml`.

## Maintenance Rules

- New test helpers that create SQLAlchemy sqlite engines should still dispose their own sessions and engines when practical.
- If a helper creates a database resource without going through `sqlalchemy.create_engine`, document that it is outside `_cleanup_sqlite_engines` coverage and add an explicit cleanup path.
- Do not add global sqlite `ResourceWarning` `filterwarnings` entries back into pytest config; failures must stay observable.

## Manual Recheck Commands

```bash
uv run pytest tests/test_sqlite_engine_cleanup_audit.py -q
make test
make coverage
make web-check
```

Python runtime differences can make raw `sqlite3.Connection` finalization timing nondeterministic, so the leak visibility check remains a manual recheck instead of a hard assertion on warning capture. Re-run with:

```bash
uv run python -W always::ResourceWarning -c 'import gc, sqlite3, tempfile; db = tempfile.NamedTemporaryFile(suffix=".db", delete=False); conn = sqlite3.connect(db.name); conn.execute("select 1"); del conn; gc.collect()'
```

Expected outcome: if the active interpreter emits raw sqlite leak warnings, they must appear unsuppressed. If no warning is emitted on that interpreter build, the audit still relies on the automated non-coverage proof above: raw `sqlite3.connect(...)` never enters `_SQLITE_ENGINES`, so the SQLAlchemy teardown helper cannot silently suppress it.
