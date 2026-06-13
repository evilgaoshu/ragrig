"""Knowledge base retrieval, role-model, and stage-model configuration helpers."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ragrig.db.models import KnowledgeBase


class RetrievalPreferenceRequest(BaseModel):
    mode: str = Field(
        default="dense",
        pattern=(
            r"^(dense|hybrid|rerank|hybrid_rerank|graph|hybrid_graph|"
            r"graph_rerank|hybrid_graph_rerank)$"
        ),
    )
    lexical_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    candidate_k: int = Field(default=20, ge=1, le=200)
    reranker_provider: str | None = Field(default=None, max_length=128)
    reranker_model: str | None = Field(default=None, max_length=256)
    graph_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    graph_depth: int = Field(default=1, ge=0, le=2)


class RoleModelConfigRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


STAGE_MODEL_POLICY_STAGES = (
    "parse",
    "understand",
    "extract",
    "query",
    "rerank",
    "answer",
    "judge",
)


class StageModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, min_length=1, max_length=128)
    model: str | None = Field(default=None, min_length=1, max_length=256)
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    budget_hint_usd: float | None = Field(default=None, ge=0.0)
    max_tokens: int | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=1000)
    tags: list[str] | None = Field(default=None, max_length=32)


class StageModelPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: dict[str, StageModelConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_stage_names(self) -> "StageModelPolicyRequest":
        unknown = sorted(set(self.policy) - set(STAGE_MODEL_POLICY_STAGES))
        if unknown:
            raise ValueError(f"unsupported stage(s): {', '.join(unknown)}")
        return self


def validate_stage_model_policy(policy: dict[str, Any]) -> str | None:
    try:
        StageModelPolicyRequest(policy=policy)
    except ValidationError as exc:
        return str(exc)
    return None


def normalized_stage_model_policy(request: StageModelPolicyRequest) -> dict[str, Any]:
    return request.model_dump(mode="json", exclude_none=True)["policy"]


def kb_stage_model_policy(knowledge_base: KnowledgeBase | None) -> dict[str, Any] | None:
    if knowledge_base is None:
        return None
    metadata = (
        knowledge_base.metadata_json if isinstance(knowledge_base.metadata_json, dict) else {}
    )
    policy = metadata.get("stage_model_policy")
    return policy if isinstance(policy, dict) else None


def public_stage_model_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    public: dict[str, Any] = {}
    for stage in STAGE_MODEL_POLICY_STAGES:
        raw = (policy or {}).get(stage)
        if not isinstance(raw, dict):
            continue
        safe = {
            field: raw[field]
            for field in (
                "provider",
                "model",
                "enabled",
                "budget_hint_usd",
                "max_tokens",
                "notes",
                "tags",
            )
            if raw.get(field) is not None
        }
        config = raw.get("config")
        if isinstance(config, dict):
            safe["has_config"] = True
            safe["config_keys"] = sorted(str(key) for key in config)
        public[stage] = safe
    return public


def _selection_values(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if key in StageModelConfig.model_fields and value is not None
    }


def stage_model_selection(
    stage: str,
    stage_model_policy: dict[str, Any] | None,
    *,
    request_values: dict[str, Any] | None = None,
    role_values: dict[str, Any] | None = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if stage not in STAGE_MODEL_POLICY_STAGES:
        raise ValueError(f"unsupported stage: {stage}")
    selection: dict[str, Any] = {"stage": stage, "source": "default", "enabled": True}
    selection.update(_selection_values(defaults))
    layers = (
        ("stage_model_policy", (stage_model_policy or {}).get(stage)),
        ("role_model_config", role_values),
        ("request", request_values),
    )
    for source, values in layers:
        normalized = _selection_values(values)
        if normalized:
            selection.update(normalized)
            selection["source"] = source
    return selection


def public_stage_model_selection(selection: dict[str, Any]) -> dict[str, Any]:
    public = {
        key: value
        for key, value in selection.items()
        if key
        in {
            "stage",
            "provider",
            "model",
            "source",
            "enabled",
            "budget_hint_usd",
            "max_tokens",
            "notes",
            "tags",
        }
    }
    if isinstance(selection.get("config"), dict):
        public["has_config"] = True
        public["config_keys"] = sorted(str(key) for key in selection["config"])
    return public


def role_model_selection(
    role: str | None,
    role_model_config: dict[str, Any] | None,
) -> tuple[dict[str, Any], str | None]:
    if not role or not role_model_config:
        return {}, None
    raw = role_model_config.get(role)
    matched_role = role
    if raw is None:
        raw = role_model_config.get("default")
        matched_role = "default" if raw is not None else role
    if raw is None:
        return {"role": role, "matched": False}, None
    if not isinstance(raw, dict):
        return {}, f"role_model_config entry for {matched_role!r} must be an object"

    selection: dict[str, Any] = {
        "role": role,
        "matched": True,
        "matched_role": matched_role,
    }
    string_fields = ("provider", "model", "answer_provider", "answer_model")
    config_fields = ("config", "answer_config")
    for field in string_fields:
        if field in raw:
            value = raw[field]
            if value is not None and not isinstance(value, str):
                return {}, f"role_model_config.{matched_role}.{field} must be a string"
            if value is not None:
                selection[field] = value
    for field in config_fields:
        if field in raw:
            value = raw[field]
            if value is not None and not isinstance(value, dict):
                return {}, f"role_model_config.{matched_role}.{field} must be an object"
            if value is not None:
                selection[field] = value
    return selection, None


def validate_role_model_config(config: dict[str, Any]) -> str | None:
    allowed_fields = {
        "provider",
        "model",
        "config",
        "answer_provider",
        "answer_model",
        "answer_config",
    }
    role_pattern = re.compile(r"^[A-Za-z0-9_.:-]+$")
    for role, entry in config.items():
        if not isinstance(role, str) or not role_pattern.fullmatch(role):
            return f"role_model_config role {role!r} must match {role_pattern.pattern}"
        if not isinstance(entry, dict):
            return f"role_model_config entry for {role!r} must be an object"
        unknown = sorted(set(entry) - allowed_fields)
        if unknown:
            return f"role_model_config.{role} has unsupported field(s): {', '.join(unknown)}"
        for field in ("provider", "model", "answer_provider", "answer_model"):
            value = entry.get(field)
            if value is not None and not isinstance(value, str):
                return f"role_model_config.{role}.{field} must be a string"
        for field in ("config", "answer_config"):
            value = entry.get(field)
            if value is not None and not isinstance(value, dict):
                return f"role_model_config.{role}.{field} must be an object"
    return None


def kb_role_model_config(knowledge_base: KnowledgeBase | None) -> dict[str, Any] | None:
    if knowledge_base is None:
        return None
    metadata = (
        knowledge_base.metadata_json if isinstance(knowledge_base.metadata_json, dict) else {}
    )
    config = metadata.get("role_model_config")
    return config if isinstance(config, dict) else None


def public_role_model_config(config: dict[str, Any] | None) -> dict[str, Any]:
    public: dict[str, Any] = {}
    for role, entry in (config or {}).items():
        if not isinstance(role, str) or not isinstance(entry, dict):
            continue
        safe = {
            field: entry[field]
            for field in ("provider", "model", "answer_provider", "answer_model")
            if isinstance(entry.get(field), str)
        }
        if isinstance(entry.get("config"), dict):
            safe["has_config"] = True
        if isinstance(entry.get("answer_config"), dict):
            safe["has_answer_config"] = True
        public[role] = safe
    return public


def public_role_model_selection(selection: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in selection.items() if key not in {"config", "answer_config"}
    }


def kb_retrieval_preferences(knowledge_base: KnowledgeBase | None) -> dict[str, Any]:
    defaults = RetrievalPreferenceRequest().model_dump(mode="json")
    if knowledge_base is None:
        return defaults
    metadata = (
        knowledge_base.metadata_json if isinstance(knowledge_base.metadata_json, dict) else {}
    )
    raw = metadata.get("retrieval_preferences")
    if not isinstance(raw, dict):
        return defaults
    try:
        return RetrievalPreferenceRequest(**raw).model_dump(mode="json")
    except ValueError:
        return defaults
