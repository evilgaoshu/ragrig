from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ragrig.answer.schema import EvidenceChunk
from ragrig.providers import ProviderError, get_provider_registry

SECRET_POLICY = "env_refs_only"
SECRET_FIELD_NAMES = {"api_key", "token", "password", "secret", "access_key", "secret_key"}
OPENAI_COMPATIBLE_PROVIDERS = {"model.lm_studio", "model.openai", "model.openrouter"}


class ModelConfigError(ValueError):
    def __init__(self, code: str, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


def _looks_secret_field(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in SECRET_FIELD_NAMES)


def _env_name(value: str) -> str | None:
    if value.startswith("env:") and len(value) > 4:
        return value[4:].strip()
    return None


def resolve_env_config(config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    resolved: dict[str, Any] = {}
    missing: list[str] = []
    for key, value in config.items():
        if isinstance(value, str):
            env_name = _env_name(value)
            if env_name is not None:
                env_value = os.getenv(env_name)
                if env_value is None:
                    missing.append(env_name)
                else:
                    resolved[key] = env_value
                continue
            if _looks_secret_field(key) and value:
                raise ModelConfigError(
                    "secret_reference_required",
                    f"field '{key}' must use env:VARIABLE_NAME",
                    field=key,
                )
        resolved[key] = value
    return resolved, sorted(set(missing))


def _safe_detail(message: str, *, missing: list[str] | None = None) -> str:
    if missing:
        return f"Missing environment variable(s): {', '.join(missing)}"
    return message


def _provider_defaults(provider: str) -> dict[str, str]:
    if provider == "model.openai":
        return {"base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"}
    if provider == "model.openrouter":
        return {
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
        }
    if provider == "model.lm_studio":
        return {"base_url": "http://localhost:1234/v1", "api_key_env": ""}
    return {}


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    encoded = None
    request_headers = dict(headers or {})
    if body is not None:
        encoded = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=encoded, headers=request_headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def model_health_check(
    *,
    provider: str,
    model: str | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = dict(config or {})
    try:
        resolved, missing = resolve_env_config(config)
    except ModelConfigError:
        raise
    except Exception as exc:
        raise ModelConfigError("model_config_invalid", str(exc)) from exc

    if missing:
        return {
            "provider": provider,
            "model": model,
            "status": "missing_credentials",
            "detail": _safe_detail("", missing=missing),
            "missing_credentials": missing,
            "secret_policy": SECRET_POLICY,
        }

    if provider == "deterministic-local":
        return {
            "provider": provider,
            "model": model or "hash-8d",
            "status": "healthy",
            "detail": "Deterministic local answer smoke provider is ready",
            "missing_credentials": [],
            "secret_policy": SECRET_POLICY,
        }

    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return _openai_compatible_health(provider=provider, model=model, config=resolved)

    try:
        provider_config = dict(resolved)
        if model:
            provider_config.setdefault("model_name", model)
        health = get_provider_registry().get(provider, **provider_config).health_check()
        return {
            "provider": provider,
            "model": model,
            "status": health.status,
            "detail": health.detail,
            "metrics": _safe_metrics(health.metrics),
            "missing_credentials": [],
            "secret_policy": SECRET_POLICY,
        }
    except ProviderError as exc:
        return {
            "provider": provider,
            "model": model,
            "status": "unavailable",
            "detail": str(exc),
            "code": exc.code,
            "missing_credentials": [],
            "secret_policy": SECRET_POLICY,
        }


def _safe_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metrics.items()
        if not _looks_secret_field(key)
        and not (isinstance(value, str) and value.startswith("env:"))
    }


def _openai_compatible_health(
    *,
    provider: str,
    model: str | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    defaults = _provider_defaults(provider)
    base_url = str(config.get("base_url") or config.get("api_base_url") or defaults["base_url"])
    api_key = config.get("api_key") or (
        os.getenv(defaults["api_key_env"]) if defaults.get("api_key_env") else None
    )
    if defaults.get("api_key_env") and not api_key:
        return {
            "provider": provider,
            "model": model,
            "status": "missing_credentials",
            "detail": _safe_detail("", missing=[defaults["api_key_env"]]),
            "missing_credentials": [defaults["api_key_env"]],
            "secret_policy": SECRET_POLICY,
        }
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        payload = _http_json(f"{base_url.rstrip('/')}/models", headers=headers)
    except Exception as exc:
        return {
            "provider": provider,
            "model": model,
            "status": "unavailable",
            "detail": f"{provider} endpoint is not reachable: {exc}",
            "missing_credentials": [],
            "secret_policy": SECRET_POLICY,
        }
    models = payload.get("data", [])
    return {
        "provider": provider,
        "model": model,
        "status": "healthy",
        "detail": f"{provider} endpoint is reachable",
        "metrics": {
            "base_url": base_url,
            "model_count": len(models) if isinstance(models, list) else 0,
        },
        "missing_credentials": [],
        "secret_policy": SECRET_POLICY,
    }


def configured_answer_smoke(
    *,
    provider: str,
    model: str | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        resolved, missing = resolve_env_config(dict(config or {}))
    except ModelConfigError:
        raise
    if missing:
        return {
            "provider": provider,
            "model": model,
            "status": "missing_credentials",
            "detail": _safe_detail("", missing=missing),
            "missing_credentials": missing,
            "secret_policy": SECRET_POLICY,
        }
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return _openai_compatible_answer_smoke(provider=provider, model=model, config=resolved)

    from ragrig.answer.provider import get_answer_provider

    try:
        answer_provider = get_answer_provider(provider, model=model, provider_config=resolved)
        answer, citation_ids = answer_provider.generate(
            "What does Local Pilot verify?", _smoke_evidence()
        )
    except Exception as exc:
        return {
            "provider": provider,
            "model": model,
            "status": "unavailable",
            "detail": str(exc),
            "secret_policy": SECRET_POLICY,
        }
    return _answer_payload(provider=provider, model=model, answer=answer, citation_ids=citation_ids)


def _smoke_evidence() -> list[EvidenceChunk]:
    return [
        EvidenceChunk(
            citation_id="cit-1",
            document_uri="local-pilot://smoke",
            chunk_id="smoke",
            chunk_index=0,
            text="RAGRig Local Pilot verifies grounded answers with citations.",
            score=1.0,
            distance=0.0,
        )
    ]


def _openai_compatible_answer_smoke(
    *,
    provider: str,
    model: str | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    defaults = _provider_defaults(provider)
    base_url = str(config.get("base_url") or config.get("api_base_url") or defaults["base_url"])
    api_key = config.get("api_key") or (
        os.getenv(defaults["api_key_env"]) if defaults.get("api_key_env") else None
    )
    if defaults.get("api_key_env") and not api_key:
        return {
            "provider": provider,
            "model": model,
            "status": "missing_credentials",
            "detail": _safe_detail("", missing=[defaults["api_key_env"]]),
            "missing_credentials": [defaults["api_key_env"]],
            "secret_policy": SECRET_POLICY,
        }
    target_model = model or str(config.get("model_name") or "local-model")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    body = {
        "model": target_model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Use only this evidence and cite [cit-1]: "
                    "RAGRig Local Pilot verifies grounded answers with citations. "
                    "Question: What does Local Pilot verify?"
                ),
            }
        ],
    }
    try:
        payload = _http_json(
            f"{base_url.rstrip('/')}/chat/completions",
            method="POST",
            headers=headers,
            body=body,
        )
        answer = str(payload.get("choices", [{}])[0].get("message", {}).get("content", ""))
    except Exception as exc:
        return {
            "provider": provider,
            "model": target_model,
            "status": "unavailable",
            "detail": f"{provider} answer smoke failed: {exc}",
            "secret_policy": SECRET_POLICY,
        }
    citation_ids = ["cit-1"] if "[cit-1]" in answer else []
    return _answer_payload(
        provider=provider, model=target_model, answer=answer, citation_ids=citation_ids
    )


def _answer_payload(
    *,
    provider: str,
    model: str | None,
    answer: str,
    citation_ids: list[str],
) -> dict[str, Any]:
    status = "healthy" if "cit-1" in citation_ids or "[cit-1]" in answer else "degraded"
    return {
        "provider": provider,
        "model": model,
        "status": status,
        "detail": answer[:240],
        "citation_ids": citation_ids,
        "secret_policy": SECRET_POLICY,
    }
