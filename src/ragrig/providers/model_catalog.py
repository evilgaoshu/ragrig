from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlencode


class ModelCatalogTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, object] | None = None,
        timeout_seconds: float = 10.0,
    ) -> tuple[int, dict[str, str], dict[str, object], float]: ...


@dataclass(frozen=True)
class ModelProviderSpec:
    provider: str
    display_name: str
    protocol: str
    official_docs_url: str
    base_url: str
    list_models_path: str
    auth_env_vars: tuple[str, ...] = ()
    base_url_env_var: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    query_env_var: str | None = None
    list_models_supported: bool = True
    speed_test_supported: bool = True
    notes: str = ""

    def resolved_base_url(self, env: dict[str, str] | os._Environ[str]) -> str:
        if self.base_url_env_var and env.get(self.base_url_env_var):
            return str(env[self.base_url_env_var]).rstrip("/")
        return self.base_url.rstrip("/")


class UrlLibModelCatalogTransport:
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, object] | None = None,
        timeout_seconds: float = 10.0,
    ) -> tuple[int, dict[str, str], dict[str, object], float]:
        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers = {**headers, "Content-Type": "application/json"}
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read()
                elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
                payload = json.loads(raw.decode("utf-8")) if raw else {}
                return response.status, dict(response.headers.items()), payload, elapsed_ms
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                payload = {"error": raw.decode("utf-8", errors="replace")}
            return exc.code, dict(exc.headers.items()), payload, elapsed_ms


MAINSTREAM_MODEL_PROVIDERS: dict[str, ModelProviderSpec] = {
    "model.openai": ModelProviderSpec(
        provider="model.openai",
        display_name="OpenAI",
        protocol="openai-compatible",
        official_docs_url="https://platform.openai.com/docs/api-reference/models/list",
        base_url="https://api.openai.com/v1",
        list_models_path="/models",
        auth_env_vars=("OPENAI_API_KEY",),
    ),
    "model.azure_openai": ModelProviderSpec(
        provider="model.azure_openai",
        display_name="Azure OpenAI",
        protocol="openai-compatible",
        official_docs_url=(
            "https://learn.microsoft.com/en-us/azure/ai-services/openai/"
            "reference-preview-latest#list-models"
        ),
        base_url="https://example-resource.openai.azure.com",
        base_url_env_var="AZURE_OPENAI_ENDPOINT",
        list_models_path="/openai/models?api-version=2025-01-01-preview",
        auth_env_vars=("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"),
    ),
    "model.anthropic": ModelProviderSpec(
        provider="model.anthropic",
        display_name="Anthropic Claude",
        protocol="anthropic",
        official_docs_url="https://docs.claude.com/en/api/models-list",
        base_url="https://api.anthropic.com/v1",
        list_models_path="/models",
        auth_env_vars=("ANTHROPIC_API_KEY",),
        extra_headers={"anthropic-version": "2023-06-01"},
    ),
    "model.google_gemini": ModelProviderSpec(
        provider="model.google_gemini",
        display_name="Google Gemini",
        protocol="gemini",
        official_docs_url="https://ai.google.dev/api/models#method:-models.list",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        list_models_path="/models",
        auth_env_vars=("GOOGLE_API_KEY",),
        query_env_var="GOOGLE_API_KEY",
    ),
    "model.bedrock": ModelProviderSpec(
        provider="model.bedrock",
        display_name="Amazon Bedrock",
        protocol="bedrock",
        official_docs_url=(
            "https://docs.aws.amazon.com/bedrock/latest/APIReference/"
            "API_ListFoundationModels.html"
        ),
        base_url="https://bedrock.us-east-1.amazonaws.com",
        list_models_path="/foundation-models",
        auth_env_vars=("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"),
        notes="Production calls require AWS SigV4; fake transport covers contract parsing.",
    ),
    "model.vertex_ai": ModelProviderSpec(
        provider="model.vertex_ai",
        display_name="Google Vertex AI",
        protocol="vertex-ai",
        official_docs_url=(
            "https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/"
            "inference"
        ),
        base_url="https://us-central1-aiplatform.googleapis.com",
        list_models_path="/v1/projects/{project}/locations/us-central1/publishers/google/models",
        auth_env_vars=("GOOGLE_APPLICATION_CREDENTIALS", "VERTEX_AI_PROJECT"),
        list_models_supported=False,
        speed_test_supported=False,
        notes="Catalog documents required config; live model listing needs project-aware auth.",
    ),
    "model.openrouter": ModelProviderSpec(
        provider="model.openrouter",
        display_name="OpenRouter",
        protocol="openai-compatible",
        official_docs_url="https://openrouter.ai/docs/api-reference/list-available-models",
        base_url="https://openrouter.ai/api/v1",
        list_models_path="/models",
        auth_env_vars=("OPENROUTER_API_KEY",),
    ),
    "model.mistral": ModelProviderSpec(
        provider="model.mistral",
        display_name="Mistral AI",
        protocol="openai-compatible",
        official_docs_url="https://docs.mistral.ai/api/",
        base_url="https://api.mistral.ai/v1",
        list_models_path="/models",
        auth_env_vars=("MISTRAL_API_KEY",),
    ),
    "model.cohere": ModelProviderSpec(
        provider="model.cohere",
        display_name="Cohere",
        protocol="cohere",
        official_docs_url="https://docs.cohere.com/reference/list-models",
        base_url="https://api.cohere.com/v2",
        list_models_path="/models",
        auth_env_vars=("COHERE_API_KEY",),
    ),
    "model.voyage": ModelProviderSpec(
        provider="model.voyage",
        display_name="Voyage AI",
        protocol="voyage",
        official_docs_url="https://docs.voyageai.com/docs/embeddings",
        base_url="https://api.voyageai.com/v1",
        list_models_path="/models",
        auth_env_vars=("VOYAGE_API_KEY",),
        list_models_supported=False,
        speed_test_supported=False,
        notes="Voyage publishes model families in docs; no stable list-model endpoint is exposed.",
    ),
    "model.jina": ModelProviderSpec(
        provider="model.jina",
        display_name="Jina AI",
        protocol="jina",
        official_docs_url="https://jina.ai/embeddings/",
        base_url="https://api.jina.ai/v1",
        list_models_path="/models",
        auth_env_vars=("JINA_API_KEY",),
        list_models_supported=False,
        speed_test_supported=False,
        notes=(
            "Jina model families are published in docs; no stable list-model endpoint is exposed."
        ),
    ),
    "model.together": ModelProviderSpec(
        provider="model.together",
        display_name="Together AI",
        protocol="openai-compatible",
        official_docs_url="https://docs.together.ai/reference/models",
        base_url="https://api.together.xyz/v1",
        list_models_path="/models",
        auth_env_vars=("TOGETHER_API_KEY",),
    ),
    "model.fireworks": ModelProviderSpec(
        provider="model.fireworks",
        display_name="Fireworks AI",
        protocol="openai-compatible",
        official_docs_url="https://fireworks.ai/docs/api-reference/list-models",
        base_url="https://api.fireworks.ai/inference/v1",
        list_models_path="/models",
        auth_env_vars=("FIREWORKS_API_KEY",),
    ),
    "model.groq": ModelProviderSpec(
        provider="model.groq",
        display_name="Groq",
        protocol="openai-compatible",
        official_docs_url="https://console.groq.com/docs/models",
        base_url="https://api.groq.com/openai/v1",
        list_models_path="/models",
        auth_env_vars=("GROQ_API_KEY",),
    ),
    "model.deepseek": ModelProviderSpec(
        provider="model.deepseek",
        display_name="DeepSeek",
        protocol="openai-compatible",
        official_docs_url="https://api-docs.deepseek.com/api/list-models",
        base_url="https://api.deepseek.com/v1",
        list_models_path="/models",
        auth_env_vars=("DEEPSEEK_API_KEY",),
    ),
    "model.moonshot": ModelProviderSpec(
        provider="model.moonshot",
        display_name="Moonshot Kimi",
        protocol="openai-compatible",
        official_docs_url="https://platform.kimi.ai/docs/api/list-models",
        base_url="https://api.moonshot.ai/v1",
        list_models_path="/models",
        auth_env_vars=("MOONSHOT_API_KEY",),
    ),
    "model.minimax": ModelProviderSpec(
        provider="model.minimax",
        display_name="MiniMax",
        protocol="openai-compatible",
        official_docs_url="https://platform.minimax.io/docs/api-reference/models/openai/list-models",
        base_url="https://api.minimax.io/v1",
        list_models_path="/models",
        auth_env_vars=("MINIMAX_API_KEY",),
    ),
    "model.dashscope": ModelProviderSpec(
        provider="model.dashscope",
        display_name="Alibaba Cloud DashScope",
        protocol="openai-compatible",
        official_docs_url=(
            "https://help.aliyun.com/zh/model-studio/"
            "compatibility-of-openai-with-dashscope"
        ),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        list_models_path="/models",
        auth_env_vars=("DASHSCOPE_API_KEY",),
    ),
    "model.siliconflow": ModelProviderSpec(
        provider="model.siliconflow",
        display_name="SiliconFlow",
        protocol="openai-compatible",
        official_docs_url="https://docs.siliconflow.cn/cn/api-reference/models/get-model-list",
        base_url="https://api.siliconflow.cn/v1",
        list_models_path="/models",
        auth_env_vars=("SILICONFLOW_API_KEY",),
    ),
    "model.zhipu": ModelProviderSpec(
        provider="model.zhipu",
        display_name="Zhipu / Z.ai GLM",
        protocol="openai-compatible",
        official_docs_url="https://docs.bigmodel.cn/",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        list_models_path="/models",
        auth_env_vars=("ZHIPU_API_KEY",),
    ),
    "model.baidu_qianfan": ModelProviderSpec(
        provider="model.baidu_qianfan",
        display_name="Baidu Qianfan",
        protocol="openai-compatible",
        official_docs_url="https://cloud.baidu.com/doc/qianfan-docs/s/qm8qxemze",
        base_url="https://qianfan.baidubce.com/v2",
        list_models_path="/models",
        auth_env_vars=("QIANFAN_API_KEY",),
    ),
    "model.volcengine_ark": ModelProviderSpec(
        provider="model.volcengine_ark",
        display_name="Volcengine Ark",
        protocol="openai-compatible",
        official_docs_url="https://www.volcengine.com/docs/82379/66619f91f281250274ef5000",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        list_models_path="/models",
        auth_env_vars=("ARK_API_KEY",),
    ),
    "model.xai": ModelProviderSpec(
        provider="model.xai",
        display_name="xAI",
        protocol="openai-compatible",
        official_docs_url="https://docs.x.ai/developers/rest-api-reference/inference/models",
        base_url="https://api.x.ai/v1",
        list_models_path="/models",
        auth_env_vars=("XAI_API_KEY",),
    ),
    "model.perplexity": ModelProviderSpec(
        provider="model.perplexity",
        display_name="Perplexity",
        protocol="openai-compatible",
        official_docs_url="https://docs.perplexity.ai/api-reference/models-get",
        base_url="https://api.perplexity.ai/v1",
        list_models_path="/models",
        auth_env_vars=("PERPLEXITY_API_KEY",),
    ),
    "model.nvidia_nim": ModelProviderSpec(
        provider="model.nvidia_nim",
        display_name="NVIDIA NIM",
        protocol="openai-compatible",
        official_docs_url=(
            "https://docs.nvidia.com/nim/large-language-models/latest/reference/"
            "api-reference.html"
        ),
        base_url="https://integrate.api.nvidia.com/v1",
        list_models_path="/models",
        auth_env_vars=("NVIDIA_API_KEY",),
    ),
    "model.openai_compatible": ModelProviderSpec(
        provider="model.openai_compatible",
        display_name="Generic OpenAI-Compatible Endpoint",
        protocol="openai-compatible",
        official_docs_url="https://platform.openai.com/docs/api-reference/models/list",
        base_url="http://localhost:8000/v1",
        base_url_env_var="OPENAI_COMPATIBLE_BASE_URL",
        list_models_path="/models",
        auth_env_vars=(),
        notes="Use OPENAI_COMPATIBLE_API_KEY when the upstream endpoint requires a bearer token.",
    ),
    "model.ollama": ModelProviderSpec(
        provider="model.ollama",
        display_name="Ollama",
        protocol="ollama",
        official_docs_url="https://github.com/ollama/ollama/blob/main/docs/api.md",
        base_url="http://localhost:11434",
        list_models_path="/api/tags",
    ),
    "model.lm_studio": ModelProviderSpec(
        provider="model.lm_studio",
        display_name="LM Studio",
        protocol="openai-compatible",
        official_docs_url="https://lmstudio.ai/docs/app/api/endpoints/openai",
        base_url="http://localhost:1234/v1",
        list_models_path="/models",
    ),
    "model.llama_cpp": ModelProviderSpec(
        provider="model.llama_cpp",
        display_name="llama.cpp server",
        protocol="openai-compatible",
        official_docs_url=(
            "https://github.com/ggml-org/llama.cpp/blob/master/examples/server/README.md"
        ),
        base_url="http://localhost:8080/v1",
        list_models_path="/models",
    ),
    "model.vllm": ModelProviderSpec(
        provider="model.vllm",
        display_name="vLLM OpenAI-Compatible Server",
        protocol="openai-compatible",
        official_docs_url="https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html",
        base_url="http://localhost:8000/v1",
        list_models_path="/models",
    ),
    "model.xinference": ModelProviderSpec(
        provider="model.xinference",
        display_name="Xinference",
        protocol="openai-compatible",
        official_docs_url="https://inference.readthedocs.io/en/latest/user_guide/openai_api.html",
        base_url="http://localhost:9997/v1",
        list_models_path="/models",
    ),
    "model.localai": ModelProviderSpec(
        provider="model.localai",
        display_name="LocalAI",
        protocol="openai-compatible",
        official_docs_url="https://localai.io/api-endpoints/",
        base_url="http://localhost:8080/v1",
        list_models_path="/models",
    ),
    "embedding.bge": ModelProviderSpec(
        provider="embedding.bge",
        display_name="BGE Embedding",
        protocol="local-runtime",
        official_docs_url="https://github.com/FlagOpen/FlagEmbedding",
        base_url="local://bge",
        list_models_path="",
        list_models_supported=False,
        speed_test_supported=False,
    ),
    "reranker.bge": ModelProviderSpec(
        provider="reranker.bge",
        display_name="BGE Reranker",
        protocol="local-runtime",
        official_docs_url="https://github.com/FlagOpen/FlagEmbedding",
        base_url="local://bge",
        list_models_path="",
        list_models_supported=False,
        speed_test_supported=False,
    ),
}


def serialize_provider_catalog() -> list[dict[str, object]]:
    return [
        {
            "provider": spec.provider,
            "display_name": spec.display_name,
            "protocol": spec.protocol,
            "official_docs_url": spec.official_docs_url,
            "base_url": spec.base_url,
            "base_url_env_var": spec.base_url_env_var,
            "list_models_path": spec.list_models_path,
            "auth_env_vars": list(spec.auth_env_vars),
            "list_models_supported": spec.list_models_supported,
            "speed_test_supported": spec.speed_test_supported,
            "notes": spec.notes,
        }
        for spec in sorted(MAINSTREAM_MODEL_PROVIDERS.values(), key=lambda item: item.provider)
    ]


def list_provider_models(
    provider_name: str,
    *,
    env: dict[str, str] | os._Environ[str] | None = None,
    transport: ModelCatalogTransport | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, object]:
    if env is None:
        env = os.environ
    spec = MAINSTREAM_MODEL_PROVIDERS.get(provider_name)
    if spec is None:
        return {
            "provider": provider_name,
            "status": "unknown_provider",
            "models": [],
            "error": f"Provider '{provider_name}' is not in the model catalog.",
        }
    if not spec.list_models_supported:
        return _base_result(spec, status="unsupported", models=[], latency_ms=None) | {
            "reason": spec.notes or "This provider does not expose a stable list-model endpoint."
        }

    missing = [name for name in spec.auth_env_vars if not env.get(name)]
    if missing:
        return _base_result(spec, status="missing_credentials", models=[], latency_ms=None) | {
            "missing_credentials": missing
        }

    transport = transport or UrlLibModelCatalogTransport()
    url = _build_list_models_url(spec, env)
    headers = _build_headers(spec, env)
    try:
        status_code, _headers, payload, latency_ms = transport.request(
            method="GET",
            url=url,
            headers=headers,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        return _base_result(spec, status="error", models=[], latency_ms=None) | {
            "error": _safe_error(exc),
        }

    models = _extract_models(payload)
    status = "ready" if 200 <= status_code < 300 else "error"
    result = _base_result(spec, status=status, models=models, latency_ms=latency_ms)
    result["status_code"] = status_code
    if status == "error":
        result["error"] = _safe_payload_error(payload)
    return result


def measure_provider_latency(
    provider_name: str,
    *,
    env: dict[str, str] | os._Environ[str] | None = None,
    transport: ModelCatalogTransport | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, object]:
    result = list_provider_models(
        provider_name,
        env=env,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    return {
        "provider": provider_name,
        "status": result["status"],
        "measurement": "model_list_latency_ms",
        "latency_ms": result.get("latency_ms"),
        "model_count": len(result.get("models", [])),
        "missing_credentials": result.get("missing_credentials", []),
        "official_docs_url": result.get("official_docs_url"),
        "error": result.get("error"),
        "reason": result.get("reason"),
    }


def _build_list_models_url(
    spec: ModelProviderSpec,
    env: dict[str, str] | os._Environ[str],
) -> str:
    url = f"{spec.resolved_base_url(env)}{spec.list_models_path}"
    if spec.query_env_var:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urlencode({'key': env[spec.query_env_var]})}"
    return url


def _build_headers(
    spec: ModelProviderSpec,
    env: dict[str, str] | os._Environ[str],
) -> dict[str, str]:
    headers = {"Accept": "application/json", **spec.extra_headers}
    credential = _first_present_credential(spec, env)
    if credential:
        if spec.protocol == "anthropic":
            headers["x-api-key"] = credential
        elif spec.protocol == "gemini":
            headers["x-goog-api-key"] = credential
        elif spec.provider == "model.azure_openai":
            headers["api-key"] = credential
        else:
            headers["Authorization"] = f"Bearer {credential}"
    return headers


def _first_present_credential(
    spec: ModelProviderSpec,
    env: dict[str, str] | os._Environ[str],
) -> str | None:
    for key in spec.auth_env_vars:
        if key.endswith("_ENDPOINT") or key in {"AWS_REGION", "VERTEX_AI_PROJECT"}:
            continue
        value = env.get(key)
        if value:
            return str(value)
    if spec.provider == "model.openai_compatible" and env.get("OPENAI_COMPATIBLE_API_KEY"):
        return str(env["OPENAI_COMPATIBLE_API_KEY"])
    return None


def _extract_models(payload: dict[str, object]) -> list[dict[str, object]]:
    raw_items = []
    if isinstance(payload.get("data"), list):
        raw_items = list(payload["data"])  # type: ignore[index]
    elif isinstance(payload.get("models"), list):
        raw_items = list(payload["models"])  # type: ignore[index]
    elif isinstance(payload.get("modelSummaries"), list):
        raw_items = list(payload["modelSummaries"])  # type: ignore[index]

    models: list[dict[str, object]] = []
    for item in raw_items:
        if isinstance(item, str):
            model_id = item
            raw: object = item
        elif isinstance(item, dict):
            model_id = _model_id_from_dict(item)
            raw = item
        else:
            continue
        if not model_id:
            continue
        models.append({"id": model_id, "raw": raw})
    return models


def _model_id_from_dict(item: dict[str, object]) -> str | None:
    for key in ("id", "name", "model", "modelId"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            if value.startswith("models/"):
                return value.split("/", 1)[1]
            return value
    return None


def _base_result(
    spec: ModelProviderSpec,
    *,
    status: str,
    models: list[dict[str, object]],
    latency_ms: float | None,
) -> dict[str, object]:
    return {
        "provider": spec.provider,
        "display_name": spec.display_name,
        "protocol": spec.protocol,
        "status": status,
        "models": models,
        "model_count": len(models),
        "latency_ms": latency_ms,
        "official_docs_url": spec.official_docs_url,
    }


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    for marker in ("sk-", "Bearer ", "api-key"):
        text = text.replace(marker, "[redacted]")
    return text[:500]


def _safe_payload_error(payload: dict[str, object]) -> str:
    for key in ("error", "message", "detail"):
        value = payload.get(key)
        if isinstance(value, str):
            return value[:500]
        if isinstance(value, dict):
            message = value.get("message")
            if isinstance(message, str):
                return message[:500]
    return "model list request failed"


__all__ = [
    "MAINSTREAM_MODEL_PROVIDERS",
    "ModelCatalogTransport",
    "ModelProviderSpec",
    "UrlLibModelCatalogTransport",
    "list_provider_models",
    "measure_provider_latency",
    "serialize_provider_catalog",
]
