"""Reranker policy smoke verification for production fallback guardrails.

This smoke is intentionally offline and deterministic.  It validates that
production does not allow the implicit fake reranker fallback, that explicit
non-production/demo allowances are observable, and that an available real
reranker provider contract is not reported as degraded.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ragrig.config import Settings
from ragrig.providers.bge import create_bge_reranker_provider
from ragrig.reranker import DEFAULT_RERANKER_PROVIDER, fake_reranker_policy

SECRET_KEY_PARTS = (
    "api_key",
    "access_key",
    "secret",
    "password",
    "token",
    "credential",
    "private_key",
    "dsn",
    "service_account",
    "session_token",
)


@dataclass(frozen=True)
class PolicyCase:
    name: str
    settings: Settings
    expected_status: str
    expected_allowed: bool
    expected_policy: str
    health_interpretation: str


class DeterministicRerankerRuntime:
    """Small injected runtime that exercises the BGE reranker provider contract."""

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        query_terms = {term for term in query.lower().split() if term}
        scores: list[float] = []
        for document in documents:
            document_terms = {term.strip(".,") for term in document.lower().split() if term}
            if not query_terms:
                scores.append(0.0)
                continue
            scores.append(len(query_terms & document_terms) / len(query_terms))
        return scores


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        redacted: dict[str, Any] = {}
        for key, value in obj.items():
            if any(part in key.lower() for part in SECRET_KEY_PARTS):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _redact(value)
        return redacted
    if isinstance(obj, list):
        return [_redact(value) for value in obj]
    return obj


def _evaluate_policy_case(case: PolicyCase) -> dict[str, Any]:
    health = fake_reranker_policy(case.settings)
    passed = (
        health["status"] == case.expected_status
        and health["fake_reranker_allowed"] is case.expected_allowed
        and health["policy"] == case.expected_policy
    )
    return {
        "name": case.name,
        "status": "pass" if passed else "fail",
        "app_env": case.settings.app_env,
        "expected": {
            "status": case.expected_status,
            "fake_reranker_allowed": case.expected_allowed,
            "policy": case.expected_policy,
        },
        "observed": health,
        "health_interpretation": case.health_interpretation,
    }


def _evaluate_real_reranker_probe() -> dict[str, Any]:
    provider = create_bge_reranker_provider(
        model_name="offline-contract-probe",
        runtime=DeterministicRerankerRuntime(),
    )
    documents = [
        "dense retrieval candidate",
        "reranker deployment validation candidate",
        "unrelated text",
    ]
    ranked = provider.rerank("reranker validation", documents)
    sorted_ranked = sorted(ranked, key=lambda item: float(item["score"]), reverse=True)
    passed = (
        provider.metadata.name == DEFAULT_RERANKER_PROVIDER
        and len(ranked) == len(documents)
        and sorted_ranked[0]["index"] == 1
        and float(sorted_ranked[0]["score"]) > 0.0
    )
    return {
        "name": "real_reranker_available_contract",
        "status": "pass" if passed else "fail",
        "provider": provider.metadata.name,
        "model": provider.model_name,
        "degraded": False if passed else True,
        "health_interpretation": (
            "An explicit real reranker provider that can score documents is available; "
            "the fake fallback policy must not be interpreted as retrieval degradation."
        ),
        "details": {
            "document_count": len(documents),
            "top_index": sorted_ranked[0]["index"] if sorted_ranked else None,
            "top_score": round(float(sorted_ranked[0]["score"]), 6) if sorted_ranked else None,
        },
    }


def run_smoke() -> dict[str, Any]:
    cases = [
        PolicyCase(
            name="production_fake_reranker_blocked",
            settings=Settings(app_env="production", ragrig_allow_fake_reranker=False),
            expected_status="blocked",
            expected_allowed=False,
            expected_policy="production_requires_real_reranker",
            health_interpretation=(
                "/health reranker.status=blocked means implicit fake fallback is blocked; "
                "production retrieval must configure an explicit real reranker or opt in."
            ),
        ),
        PolicyCase(
            name="local_fake_reranker_allowed",
            settings=Settings(app_env="development", ragrig_allow_fake_reranker=False),
            expected_status="development_fallback_allowed",
            expected_allowed=True,
            expected_policy="non_production_fallback",
            health_interpretation=(
                "/health reports local fallback allowance for development and demos."
            ),
        ),
        PolicyCase(
            name="test_explicit_fake_reranker_allowed",
            settings=Settings(app_env="test", ragrig_allow_fake_reranker=True),
            expected_status="override_allowed",
            expected_allowed=True,
            expected_policy="explicit_override",
            health_interpretation=(
                "/health reports explicit override allowance; this must be deliberate."
            ),
        ),
    ]
    checks = [_evaluate_policy_case(case) for case in cases]
    checks.append(_evaluate_real_reranker_probe())

    failed = [check["name"] for check in checks if check["status"] != "pass"]
    return {
        "test": "reranker_policy_smoke",
        "status": "pass" if not failed else "fail",
        "failed_checks": failed,
        "checks": checks,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run reranker policy smoke verification.")
    parser.add_argument("--output", default=None, help="Optional JSON output path.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = _redact(run_smoke())
    json_output = json.dumps(
        result,
        indent=2 if args.pretty else None,
        ensure_ascii=False,
        sort_keys=True,
    )
    print(json_output)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_output, encoding="utf-8")
        print(f"\nReranker policy smoke result written to {output_path}", file=sys.stderr)

    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
