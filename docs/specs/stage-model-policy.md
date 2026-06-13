# Stage-specific Model Policy

## Purpose

Each knowledge base can store a stage-specific provider/model policy in
`KnowledgeBase.metadata_json["stage_model_policy"]`. The policy complements the existing
`role_model_config`; it does not replace it.

Selection priority is:

`request override > role_model_config > stage_model_policy > endpoint default`

`role_model_config` remains a compatibility layer for query/retrieval and answer selection.

## Stages

- `parse`: parser/service visibility. P1 stores and exposes this selection, but parser service
  execution remains configured by the existing advanced-parser settings and environment.
- `understand`: document understanding provider/model and optional `config.profile_id`.
- `extract`: provider-backed Graph-RAG extraction provider/model/config.
- `query`: retrieval query embedding provider/model/config, including answer-time retrieval.
- `rerank`: reranker provider/model/config.
- `answer`: grounded answer generation provider/model/config.
- `judge`: optional answer faithfulness provider/model/config.

## API

- `GET /knowledge-bases/{kb_id}/stage-model-policy`
- `PUT /knowledge-bases/{kb_id}/stage-model-policy`

Example:

```json
{
  "policy": {
    "parse": {
      "provider": "docling-service",
      "enabled": false
    },
    "understand": {
      "provider": "openai",
      "model": "gpt-4.1-mini",
      "config": {
        "api_key": "env:OPENAI_API_KEY",
        "profile_id": "policy.understand.v1"
      },
      "budget_hint_usd": 0.02
    },
    "extract": {
      "provider": "openai",
      "model": "gpt-4.1-mini"
    },
    "query": {
      "provider": "deterministic-local"
    },
    "rerank": {
      "provider": "reranker.bge",
      "model": "BAAI/bge-reranker-v2-m3"
    },
    "answer": {
      "provider": "openai",
      "model": "gpt-4.1-mini",
      "max_tokens": 1200
    },
    "judge": {
      "provider": "openai",
      "model": "gpt-4.1-mini",
      "enabled": true
    }
  }
}
```

Allowed fields per stage are `provider`, `model`, `config`, `enabled`, `budget_hint_usd`,
`max_tokens`, `notes`, and `tags`. Unknown stages/fields and invalid value types are rejected.

## Secrets And Public Responses

Runtime config supports the existing `env:VARIABLE` convention and is resolved only when a stage
runs. Missing variables produce a stable validation/degraded response. Public GET/PUT responses
never return config values; they return only `has_config` and `config_keys`.

The Web Console JSON editor therefore omits config values. Saving a stage without a `config` field
preserves its existing stored config; sending `"config": {}` explicitly clears it.

## Trace And Usage

Answer responses expose `stage_model_selection` at the top level and inside `retrieval_trace`.
Each public selection includes stage, provider, model, source, and enabled state without secret
values. Usage-event metadata records the matching stage and public model selection for query
embedding, rerank, answer generation, and faithfulness judge operations.

Graph rebuild traces expose the `extract` selection. Understand-all responses expose the
`understand` selection and effective profile ID.

## Current Boundaries

- Default quickstart behavior remains deterministic when no policy exists.
- Parse policy is stored/displayed but does not replace advanced parser service configuration.
- Role policy applies only to query/retrieval and answer, preserving existing behavior.
- Query model selection must still match the indexed embedding profile.
- Query rewrite and HyDE retain their existing request/config paths; this slice applies the query
  stage policy to query embedding.
- Stage cost budgets are hints for audit/UI; workspace budget enforcement remains the hard limit.
