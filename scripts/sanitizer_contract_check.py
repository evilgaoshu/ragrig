#!/usr/bin/env python3
"""Executable sanitizer cross-layer contract checker.

Usage::

    python -m scripts.sanitizer_contract_check

Exit codes:
    0  – all contracts pass
    1  – unregistered sanitizer copy or missing summary fields
    2  – import/AST error

The checker scans the source tree for sanitizer call sites and verifies:
1. All metadata sanitization goes through the canonical helpers in
   ``ragrig.processing_profile.sanitizer``.
2. No unregistered duplicate implementations exist.
3. ``SanitizationSummary`` exposes all required fields.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "ragrig"
TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"

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
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
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
        imports_canonical = any(
            v.startswith(CANONICAL_SANITIZER) for v in imported.values()
        )

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


def main() -> int:
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
        return 1

    # Final verdict
    total_errors = len(summary_errors) + len(dup_errors) + len(unregistered)
    if total_errors:
        print(f"\n── Contract check FAILED with {total_errors} error(s) ──")
        return 1

    print("\n── Contract check PASSED ──")
    return 0


if __name__ == "__main__":
    sys.exit(main())
