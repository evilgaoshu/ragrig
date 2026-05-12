#!/usr/bin/env python3
"""Executable sanitizer cross-layer contract checker.

Usage::

    python -m scripts.sanitizer_contract_check [--json-output <path>] [--markdown-output <path>]

Exit codes:
    0  – all contracts pass
    1  – unregistered sanitizer copy or missing summary fields
    2  – import/AST error

The checker scans the source tree for sanitizer call sites and verifies:
1. All metadata sanitization goes through the canonical helpers in
   ``ragrig.processing_profile.sanitizer``.
2. No unregistered duplicate implementations exist.
3. ``SanitizationSummary`` exposes all required fields.

Outputs a callsite matrix as JSON and Markdown artifacts with fields:
callsite, layer, registered, summary_fields_ok, status, reason.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "ragrig"
TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON_OUTPUT = (
    REPO_ROOT / "docs" / "operations" / "artifacts" / "sanitizer-contract-matrix.json"
)
DEFAULT_MD_OUTPUT = REPO_ROOT / "docs" / "operations" / "artifacts" / "sanitizer-contract-matrix.md"
ARTIFACT_VERSION = "1.0.0"

FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
    "sk-live-",
    "sk-proj-",
    "sk-ant-",
    "ghp_",
    "Bearer ",
    "PRIVATE KEY-----",
    "super_secret_db_pass",
    "db-super-secret-999",
    "prod-api-secret-key-2024",
)

# Canonical sanitizer module path
CANONICAL_SANITIZER = "ragrig.processing_profile.sanitizer"
CANONICAL_SYMBOLS = {
    "redact_metadata",
    "remove_metadata",
    "redact_state",
    "SanitizationSummary",
    "is_sensitive_key",
    "is_sensitive_value",
}

# Registered wrapper modules that are allowed to import from the canonical module
REGISTERED_WRAPPER_MODULES = {
    "ragrig.repositories.processing_profile",
    "ragrig.processing_profile.models",
}

# Registered call sites (function names that are allowed to invoke sanitizers)
REGISTERED_CALL_SITES = {
    # repository wrappers
    "_sanitize_metadata_json",
    "_sanitize_state",
    "_is_sensitive_key",
    "_is_sensitive_value",
    # model wrapper
    "_sanitize_metadata",
    # API serialization
    "to_api_dict",
    # registry / orchestration
    "build_api_profile_list",
    "build_matrix",
}

REQUIRED_SUMMARY_FIELDS = {
    "schema_version",
    "redacted_count",
    "removed_count",
    "degraded_count",
    "non_string_key_count",
    "max_depth_exceeded",
}


def _walk_ast(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _find_function_defs(
    tree: ast.AST,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _find_class_defs(tree: ast.AST) -> list[ast.ClassDef]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]


def _get_imported_names(tree: ast.AST) -> dict[str, str]:
    """Return a map of local_name -> fully_qualified_symbol."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                names[local] = f"{module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                names[local] = alias.name
    return names


def _function_calls_sanitizer(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    imported: dict[str, str],
) -> bool:
    """Return True if *func* body calls any canonical sanitizer symbol."""
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                fqn = imported.get(node.func.id, node.func.id)
                if fqn in {f"{CANONICAL_SANITIZER}.{s}" for s in CANONICAL_SYMBOLS}:
                    return True
            elif isinstance(node.func, ast.Attribute):
                # e.g. remove_metadata(...) directly (unqualified)
                if node.func.attr in CANONICAL_SYMBOLS:
                    return True
    return False


def _scan_call_sites() -> list[dict[str, Any]]:
    """Scan source for sanitizer call sites."""
    sites: list[dict[str, Any]] = []

    for py_file in sorted(SRC_DIR.rglob("*.py")):
        rel_module = str(py_file.relative_to(SRC_DIR.parent.parent / "src")).replace("/", ".")[:-3]
        try:
            tree = _walk_ast(py_file)
        except SyntaxError:
            continue

        imported = _get_imported_names(tree)
        funcs = _find_function_defs(tree)
        classes = _find_class_defs(tree)

        # Collect methods inside classes too
        all_funcs = list(funcs)
        for cls in classes:
            for item in cls.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    all_funcs.append(item)

        for func in all_funcs:
            if _function_calls_sanitizer(func, imported):
                sites.append(
                    {
                        "module": rel_module,
                        "function": func.name,
                        "line": func.lineno,
                        "registered": func.name in REGISTERED_CALL_SITES
                        or rel_module == CANONICAL_SANITIZER,
                    }
                )

    return sites


def _check_summary_fields() -> list[str]:
    """Verify SanitizationSummary exposes all required fields."""
    errors: list[str] = []
    try:
        from ragrig.processing_profile.sanitizer import SanitizationSummary

        instance = SanitizationSummary()
        missing = REQUIRED_SUMMARY_FIELDS - set(instance.to_dict().keys())
        if missing:
            errors.append(f"SanitizationSummary.to_dict() missing fields: {sorted(missing)}")
    except Exception as exc:  # pragma: no cover
        errors.append(f"Failed to inspect SanitizationSummary: {exc}")
    return errors


def _check_no_duplicate_impls() -> list[str]:
    """Search for unregistered duplicate sanitization implementations."""
    errors: list[str] = []

    for py_file in sorted(SRC_DIR.rglob("*.py")):
        rel_module = str(py_file.relative_to(SRC_DIR.parent.parent / "src")).replace("/", ".")[:-3]
        if rel_module == CANONICAL_SANITIZER:
            continue

        try:
            tree = _walk_ast(py_file)
        except SyntaxError:
            continue

        imported = _get_imported_names(tree)
        # Check if this module imports from canonical sanitizer
        imports_canonical = any(v.startswith(CANONICAL_SANITIZER) for v in imported.values())

        if not imports_canonical and rel_module not in REGISTERED_WRAPPER_MODULES:
            # Look for suspicious patterns that suggest a copy-paste implementation
            source = py_file.read_text(encoding="utf-8")
            suspicious = [
                "redacted_count",
                "removed_count",
                "degraded_count",
                "non_string_key_count",
                "max_depth_exceeded",
            ]
            if all(p in source for p in suspicious):
                # If it contains all summary fields but doesn't import canonical,
                # it might be a duplicate implementation
                errors.append(
                    f"Potential unregistered sanitizer copy: {rel_module} "
                    f"(contains all summary fields but does not import {CANONICAL_SANITIZER})"
                )

    return errors


def _assert_no_raw_secrets(data: object, source: str) -> None:
    """Panic if any string value contains a forbidden fragment."""
    if isinstance(data, str):
        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment in data:
                raise RuntimeError(f"{source}: raw secret fragment '{fragment}' detected in output")
    elif isinstance(data, dict):
        for k, v in data.items():
            _assert_no_raw_secrets(v, f"{source}.{k}")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            _assert_no_raw_secrets(v, f"{source}[{i}]")


def _build_callsite_matrix(
    sites: list[dict[str, Any]],
    summary_errors: list[str],
    dup_errors: list[str],
    fixture_ok: bool,
) -> list[dict[str, Any]]:
    """Build a callsite matrix from scan results.

    Each row: callsite, layer, registered, summary_fields_ok, status, reason.
    """
    matrix: list[dict[str, Any]] = []
    for s in sites:
        callsite = f"{s['module']}:{s['function']}"
        layer = s["module"].split(".")[0] if "." in s["module"] else s["module"]
        registered = s["registered"]
        status = "pass" if registered else "unregistered"
        reason = ""
        if not registered:
            reason = "call site not in REGISTERED_CALL_SITES"
        matrix.append(
            {
                "callsite": callsite,
                "layer": layer,
                "registered": registered,
                "summary_fields_ok": len(summary_errors) == 0,
                "status": status,
                "reason": reason,
            }
        )

    # If there are summary or dup errors, add synthetic failure rows
    if summary_errors:
        for e in summary_errors:
            matrix.append(
                {
                    "callsite": "_check_summary_fields",
                    "layer": "contract_check",
                    "registered": False,
                    "summary_fields_ok": False,
                    "status": "failure",
                    "reason": e,
                }
            )

    if dup_errors:
        for e in dup_errors:
            matrix.append(
                {
                    "callsite": "_check_no_duplicate_impls",
                    "layer": "contract_check",
                    "registered": False,
                    "summary_fields_ok": True,
                    "status": "failure",
                    "reason": e,
                }
            )

    if not fixture_ok:
        matrix.append(
            {
                "callsite": "fixture_smoke_contract",
                "layer": "contract_check",
                "registered": True,
                "summary_fields_ok": True,
                "status": "failure",
                "reason": "fixture smoke contract failed",
            }
        )

    return matrix


def _build_artifact(
    sites: list[dict[str, Any]],
    summary_errors: list[str],
    dup_errors: list[str],
    fixture_ok: bool,
    exit_code: int,
) -> dict[str, Any]:
    """Build the full versioned contract matrix artifact."""
    matrix = _build_callsite_matrix(sites, summary_errors, dup_errors, fixture_ok)
    registered_count = sum(1 for r in matrix if r.get("registered") and r["status"] != "failure")

    status = "pass"
    if exit_code != 0:
        status = "failure"
    elif any(r["status"] in ("failure", "unregistered") for r in matrix):
        status = "degraded"

    artifact = {
        "artifact": "sanitizer-contract-matrix",
        "version": ARTIFACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "exit_code": exit_code,
        "totals": {
            "callsites": len(sites),
            "registered": registered_count,
            "unregistered": len([r for r in matrix if not r.get("registered")]),
            "summary_fields_ok": len(summary_errors) == 0,
            "no_duplicate_impls": len(dup_errors) == 0,
            "fixture_ok": fixture_ok,
        },
        "matrix": matrix,
    }
    _assert_no_raw_secrets(artifact, "sanitizer-contract-matrix")
    return artifact


def _write_json_artifact(artifact: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  JSON artifact: {path}")


def _write_markdown_artifact(artifact: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Sanitizer Contract Matrix")
    lines.append("")
    lines.append(f"- **Status**: {artifact['status']}")
    lines.append(f"- **Generated At**: {artifact['generated_at']}")
    lines.append(f"- **Artifact Version**: {artifact['version']}")
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    t = artifact["totals"]
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Callsites | {t['callsites']} |")
    lines.append(f"| Registered | {t['registered']} |")
    lines.append(f"| Unregistered | {t['unregistered']} |")
    lines.append(f"| Summary Fields OK | {t['summary_fields_ok']} |")
    lines.append(f"| No Duplicate Impls | {t['no_duplicate_impls']} |")
    lines.append(f"| Fixture OK | {t['fixture_ok']} |")
    lines.append("")
    lines.append("## Callsite Matrix")
    lines.append("")
    lines.append("| Callsite | Layer | Registered | Summary Fields OK | Status | Reason |")
    lines.append("|----------|-------|------------|-------------------|--------|--------|")
    for row in artifact["matrix"]:
        status_pill = row["status"]
        reason = (row["reason"] or "").replace("|", "\\|")
        lines.append(
            f"| {row['callsite']} | {row['layer']} | {row['registered']} | "
            f"{row['summary_fields_ok']} | {status_pill} | {reason} |"
        )
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  Markdown artifact: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sanitizer cross-layer contract checker")
    parser.add_argument(
        "--json-output", type=Path, default=DEFAULT_JSON_OUTPUT, help="JSON output path"
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_MD_OUTPUT,
        help="Markdown output path",
    )
    args = parser.parse_args(argv)

    print("── Sanitizer Cross-Layer Contract Checker ──\n")

    # 1. Summary field contract
    summary_errors = _check_summary_fields()
    if summary_errors:
        print("[FAIL] Summary field contract:")
        for e in summary_errors:
            print(f"  - {e}")
    else:
        print("[PASS] SanitizationSummary exposes all required fields.")
        print(f"       Fields: {sorted(REQUIRED_SUMMARY_FIELDS)}")

    # 2. Duplicate implementation guard
    dup_errors = _check_no_duplicate_impls()
    if dup_errors:
        print("\n[FAIL] Duplicate implementation guard:")
        for e in dup_errors:
            print(f"  - {e}")
    else:
        print("\n[PASS] No unregistered sanitizer copies detected.")

    # 3. Call site inventory
    sites = _scan_call_sites()
    registered = [s for s in sites if s["registered"]]
    unregistered = [s for s in sites if not s["registered"]]

    print(f"\n[INFO] Registered call sites: {len(registered)}")
    for s in registered:
        print(f"       {s['module']}:{s['line']}  {s['function']}")

    if unregistered:
        print(f"\n[FAIL] Unregistered call sites: {len(unregistered)}")
        for s in unregistered:
            print(f"       {s['module']}:{s['line']}  {s['function']}")
    else:
        print("\n[PASS] All sanitizer call sites are registered.")

    # 4. Cross-layer fixture contract (quick smoke)
    print("\n[INFO] Running fixture smoke contract...")
    fixture_ok = True
    try:
        from ragrig.processing_profile.models import _sanitize_metadata
        from ragrig.processing_profile.sanitizer import remove_metadata
        from ragrig.repositories.processing_profile import _sanitize_metadata_json

        fixture = {
            "api_key": "sk-test",
            "nested": {"token": "t1", "name": "ok"},
            "items": [{"secret": "s1", "id": 1}],
        }

        _, model_summary = _sanitize_metadata(fixture)
        _, sanitizer_summary = remove_metadata(fixture)
        _, _, _, repo_summary = _sanitize_metadata_json(fixture)

        assert model_summary == sanitizer_summary, "model != sanitizer"
        assert repo_summary.redacted_count == sanitizer_summary.removed_count, (
            "repo redacted_count != sanitizer removed_count"
        )
        print("[PASS] Fixture smoke contract (sanitizer == model, repo counts match).")
    except Exception as exc:
        print(f"[FAIL] Fixture smoke contract: {exc}")
        fixture_ok = False

    # Final verdict
    total_errors = len(summary_errors) + len(dup_errors) + len(unregistered)
    exit_code = 0
    if total_errors:
        print(f"\n── Contract check FAILED with {total_errors} error(s) ──")
        exit_code = 1
    elif not fixture_ok:
        print("\n── Contract check FAILED (fixture smoke contract) ──")
        exit_code = 1
    else:
        print("\n── Contract check PASSED ──")

    # Build and write artifact
    artifact = _build_artifact(sites, summary_errors, dup_errors, fixture_ok, exit_code)

    print("\n── Writing contract matrix artifacts ──")
    _write_json_artifact(artifact, args.json_output)
    _write_markdown_artifact(artifact, args.markdown_output)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
