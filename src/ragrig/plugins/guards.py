from __future__ import annotations

from importlib.util import find_spec


def is_dependency_available(import_name: str) -> bool:
    return find_spec(import_name) is not None


def list_missing_dependencies(import_names: tuple[str, ...]) -> list[str]:
    return [import_name for import_name in import_names if not is_dependency_available(import_name)]
