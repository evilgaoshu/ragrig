"""Knowledge base retrieval and role-model configuration helpers."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

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
