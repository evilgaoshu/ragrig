from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps


class NoopSpan:
    def set_attribute(self, _key: str, _value: object) -> None:
        return None

    def record_exception(self, _exception: BaseException) -> None:
        return None

    def set_status(self, _status: object) -> None:
        return None


def hash_attribute(value: object | None, *, prefix: str = "h") -> str | None:
    if value is None:
        return None
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


@contextmanager
def start_span(name: str, **attributes: object):
    try:
        from opentelemetry import trace
    except Exception:
        yield NoopSpan()
        return

    tracer = trace.get_tracer("ragrig")
    try:
        span_context = tracer.start_as_current_span(name)
    except Exception:
        yield NoopSpan()
        return

    with span_context as span:
        set_span_attributes(span, **attributes)
        try:
            yield span
        except Exception as exc:
            record_span_exception(span, exc)
            raise


def set_span_attributes(span: object, **attributes: object) -> None:
    set_attribute = getattr(span, "set_attribute", None)
    if not callable(set_attribute):
        return
    for key, value in attributes.items():
        clean = _span_value(value)
        if clean is not None:
            set_attribute(key, clean)


def record_span_exception(span: object, exc: BaseException) -> None:
    record_exception = getattr(span, "record_exception", None)
    if callable(record_exception):
        record_exception(exc)
    try:
        from opentelemetry.trace import Status, StatusCode
    except Exception:
        return
    set_status = getattr(span, "set_status", None)
    if callable(set_status):
        set_status(Status(StatusCode.ERROR, str(exc)[:240]))


def trace_function(
    name: str,
    *,
    attributes: Callable[..., dict[str, object]] | None = None,
    result_attributes: Callable[[object], dict[str, object]] | None = None,
):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            span_attributes = attributes(*args, **kwargs) if attributes is not None else {}
            with start_span(name, **span_attributes) as span:
                result = func(*args, **kwargs)
                if result_attributes is not None:
                    set_span_attributes(span, **result_attributes(result))
                return result

        return wrapper

    return decorator


def _span_value(value: object) -> bool | int | float | str | list[bool | int | float | str] | None:
    if value is None:
        return None
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple):
        values: list[bool | int | float | str] = []
        for item in value:
            if isinstance(item, bool | int | float | str):
                values.append(item)
        return values
    return str(value)
