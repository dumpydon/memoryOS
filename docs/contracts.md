# MemoryOS shared contracts

This document is the frozen T0 boundary for the API, web client, database, graph, and MCP workers. Python Pydantic models in `apps/api/src/memoryos/contracts/` are the source of truth. Any TypeScript client should be generated from OpenAPI rather than maintaining a second copy of these shapes.

## Identity and modes

- Every request carries a `scope_id` UUID. A scope is the isolated memory namespace for one demo agent/project.
- MVP authentication uses one owner API token. The token is a transport concern; a supplied scope is never permission by itself.
- `mode` is `demo` or `live`. Demo uses recorded extraction/relationship outputs and deterministic fixture embeddings labelled `demo-fixture-v1`; live uses the configured OpenAI providers. Demo never presents fixture vectors as OpenAI embeddings.
- Public demo access is limited to the fixed seeded demo scope `00000000-0000-0000-0000-000000000001`, read-only explorer/recall, preview ingestion, and allowlisted scenarios/queries. The owner token is required for mutations, arbitrary ingestion, arbitrary recall, live mode, and any non-demo scope. The default private/live scope is `00000000-0000-0000-0000-000000000002`.
- Recall only compares memories whose `embedding_model` and dimension match the query provider. Demo memories use `demo-fixture-v1`; live memories use the configured OpenAI embedding model. This prevents fixture and live vector spaces from being mixed.
- Committed interaction ingestion requires an idempotency key. Reusing a key with a different request hash is a conflict.
- Timestamps are timezone-aware UTC ISO-8601 values. When a request omits `occurred_at`, the service uses the receive time.

## Domain enums

`MemoryType`: `preference`, `semantic`, `episodic`, `procedural`.

`MemoryStatus`: `active`, `disputed`, `superseded`, `forgotten`.

`InteractionStatus`: `received`, `processing`, `completed`, `preview`, `failed`.

`IngestDecisionType`: `created`, `reinforced`, `superseded`, `disputed`, `skipped`, `rejected`.

`MemoryRelation`: `new`, `reinforce`, `supersede`, `dispute`, `skip`.

`MemoryEventType`: `created`, `reinforced`, `superseded`, `disputed`, `forgotten`, `resolved`, `expired`.

## Ingestion

`POST /v1/interactions` accepts:

```json
{
  "scope_id": "00000000-0000-0000-0000-000000000001",
  "text": "For Atlas, keep answers concise and use Python examples.",
  "source_ref": "demo:preference-python",
  "occurred_at": "2026-01-15T12:00:00Z",
  "idempotency_key": "demo-preference-python-v1",
  "mode": "demo",
  "preview": false,
  "metadata": {}
}
```

The graph returns a bounded list of candidate decisions. A candidate contains atomic content, one memory type, subject/context/attribute keys, importance and confidence in `[0,1]`, supporting evidence, and optional effective/expiry times. Model proposals are not writes until deterministic validation succeeds.

The response contains `interaction_id`, `status`, `mode`, `decisions`, affected `memory_ids`, `warnings`, and `trace` timings. Decisions include `decision_type`, `candidate_id`, optional existing/related memory IDs, `reason_code`, and a human-readable `reason_summary`.

## Memory records and history

A memory response includes `id`, `scope_id`, `lineage_id`, `version`, immutable `content`, `memory_type`, `status`, optional `subject`, `context_key`, and `attribute_key`, normalized `importance` and `confidence`, `reinforcement_count`, timestamps, optional `expires_at`, and optional `superseded_by_id`.

It also includes `why`, a bounded list of deterministic reasons derived from validated evidence, policy outcomes, and confirmation history. Existing rows with no stored Phase 2 explanation receive a deterministic fallback at read time.

`GET /v1/memories/{id}/history` returns every version and event in the lineage. Content is never edited in place when a fact changes. `POST /v1/memories/{id}/forget` soft-forgets the lineage. `POST /v1/memories/{id}/resolve` selects a version for a dispute and records a resolution event.

## Review and consolidation

`GET /v1/reviews` returns durable conflict and consolidation items with candidate/current/source snapshots, proposed relationship, evidence, confidence, and the reason automation paused. `POST /v1/reviews/{id}/resolve` accepts one owner action: `keep_both`, `use_new`, `keep_existing`, or `invalid`. A resolution records events and preserves historical versions. `keep_both` creates a separate active lineage when necessary to preserve the one-active-version-per-lineage invariant.

`POST /v1/consolidations/propose` accepts three to eight source memory IDs. Sources must be active semantic or episodic memories with the same identity/context, compatible embeddings, and conservative pairwise similarity. The proposal remains pending until owner review; approval creates a source-linked memory from the normalized source-vector centroid and leaves every source active.

## Recall and scoring

`POST /v1/recall` accepts `scope_id`, `query`, optional `limit` (default `5`, maximum `20`), optional `memory_types`, optional `min_similarity` (default `0.25`), optional `include_disputed`, optional `as_of`, and `mode`.

Every result exposes the memory plus a `score` breakdown. `raw_similarity` preserves the cosine value in `[-1,1]`; `similarity` is the clamped `[0,1]` value used by the formula:

```text
S = clamp(cosine_similarity, 0, 1)
I = importance
C = confidence
R = 2 ^ (-days_since_last_confirmation / half_life_for_type)
F = min(1, log(1 + reinforcement_count) / log(6))
score = 0.55*S + 0.15*I + 0.10*R + 0.10*F + 0.10*C
```

Initial half-lives are preference `180`, semantic `365`, episodic `30`, and procedural `180` days. Decay is calculated at recall time; it does not delete a memory. Results include raw similarity, normalized factors, weighted contributions, the policy version, evaluation time, and a deterministic explanation.

`POST /v1/recall/compare` evaluates naive similarity and MemoryOS ranking from the same query embedding, snapshot, timestamp, filters, and relevance floor. This endpoint exists for Recall Lab and must not make either side an unfair baseline.

## REST surface

- `GET /health/live`: process is alive.
- `GET /health/ready`: database/provider readiness.
- `POST /v1/interactions`: ingest or preview an interaction.
- `GET /v1/interactions/{interaction_id}`: inspect decisions and trace.
- `GET /v1/memories`: filter/paginate the explorer.
- `GET /v1/memories/{memory_id}`: memory detail.
- `GET /v1/memories/{memory_id}/history`: lineage history.
- `POST /v1/memories/{memory_id}/forget`: soft-forget a lineage.
- `POST /v1/memories/{memory_id}/resolve`: resolve a dispute.
- `POST /v1/recall`: explainable retrieval.
- `POST /v1/recall/compare`: naive vs MemoryOS ranking.
- `GET /v1/overview`: dashboard counts and recent activity.
- `GET /v1/capabilities`: non-secret live-provider configuration readiness.
- `GET /v1/reviews`: list pending or resolved review items.
- `POST /v1/reviews/{review_id}/resolve`: apply an audited owner decision.
- `POST /v1/consolidations/propose`: create a conservative review-first proposal.
- `GET /v1/demo/scenarios`: safe demo replay scenarios.

Errors are `{ "code": string, "message": string, "request_id": string, "retryable": boolean }`. Transport uses `auth_required` for missing owner credentials, `scope_forbidden` for non-demo scopes in public mode, `demo_input_not_allowed` for unlisted public inputs, and `idempotency_conflict` for a reused key with different text.

## MCP surface

The MCP server exposes `remember`, `recall`, `forget`, and `list_memories`. Tool input/output fields map to the REST services above. They must never duplicate ranking, policy, or persistence code. Streamable HTTP is the deployed transport and stdio is available for local clients.
