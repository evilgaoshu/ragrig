from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

import pytest

import ragrig.formats.registry as formats_mod
import ragrig.plugins as plugins_mod
import ragrig.providers as providers_mod

pytestmark = pytest.mark.unit

T = TypeVar("T")


def _run_concurrently(factory: Callable[[], T], *, count: int = 16) -> list[T]:
    barrier = threading.Barrier(count)
    errors: list[BaseException] = []
    results: list[T] = []
    result_lock = threading.Lock()

    def worker() -> None:
        try:
            barrier.wait()
            result = factory()
            with result_lock:
                results.append(result)
        except BaseException as exc:
            with result_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == count
    return results


def test_plugin_registry_singleton_initializes_once_across_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class FakeRegistry:
        pass

    def build_registry() -> FakeRegistry:
        nonlocal calls
        time.sleep(0.01)
        calls += 1
        return FakeRegistry()

    monkeypatch.setattr(plugins_mod, "_REGISTRY", None)
    monkeypatch.setattr(plugins_mod, "build_plugin_registry", build_registry)

    registries = _run_concurrently(plugins_mod.get_plugin_registry)

    assert len({id(registry) for registry in registries}) == 1
    assert calls == 1


def test_format_registry_singleton_initializes_once_across_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class FakeRegistry:
        pass

    def create_registry() -> FakeRegistry:
        nonlocal calls
        time.sleep(0.01)
        calls += 1
        return FakeRegistry()

    monkeypatch.setattr(formats_mod, "_REGISTRY", None)
    monkeypatch.setattr(formats_mod, "SupportedFormatRegistry", create_registry)

    registries = _run_concurrently(formats_mod.get_format_registry)

    assert len({id(registry) for registry in registries}) == 1
    assert calls == 1


def test_provider_registry_singleton_initializes_once_across_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class FakeRegistry:
        pass

    def create_registry() -> FakeRegistry:
        nonlocal calls
        time.sleep(0.01)
        calls += 1
        return FakeRegistry()

    monkeypatch.setattr(providers_mod, "_provider_registry", None)
    monkeypatch.setattr(providers_mod, "create_provider_registry", create_registry)

    registries = _run_concurrently(providers_mod.get_provider_registry)

    assert len({id(registry) for registry in registries}) == 1
    assert calls == 1
