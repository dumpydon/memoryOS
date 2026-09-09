# T4 ingestion handoff

`MemoryIngestionService(settings, session_factory)` is the synchronous service
used by REST and MCP. It keeps provider work outside the mutation transaction,
then commits one validated interaction plan through the scoped repository
revision guard. A provider failure therefore cannot create an interaction,
advance a scope revision, or leave a partial memory/event batch.

## Provider seam

`memoryos.providers.factory` is shared by ingestion and query workers:

```python
make_embedding_provider(mode, settings)
make_structured_provider(mode, settings)
```

Demo providers delegate only to authored `memoryos.seed.catalog` fixtures.
They return the configured `demo-fixture-v1` model and validated 1536-D vectors,
reject unknown fixture text, cap extraction at five candidates, and cap related
memory input at five per candidate. Demo relation targets are selected from
active memories first, then disputed memories, by matching memory type and
subject/context/attribute keys. No target produces `new`, except the fixture's
unsupported reinforce case, which is left for deterministic policy rejection.

Live providers use the configured OpenAI model with a 30-second client timeout
and one SDK retry. Structured responses use parsed Pydantic schemas, reject
missing or duplicate relation rows and foreign IDs, and never expose provider
payloads through `ServiceError`. Prompts label all source/candidate/memory text
as untrusted data and describe the four supported memory types and canonical
identity keys. No arbitrary model tools are enabled.

## Graph execution

`build_ingestion_graph` compiles these bounded stages:

```text
extract -> embed -> find_related -> assess_relations -> validate_plan -> persist
```

An empty extraction skips `embed`; a related-memory snapshot with no rows skips
the second structured call. The service invokes the graph with recursion limit
12. Each executed node records elapsed milliseconds in `InteractionTrace`,
including the persist stage. Normal committed ingestion uses at most one
structured extraction call and one relation call, plus one embedding call for
the candidate batch. Candidate effective time is copied from `occurred_at` only
when the provider omitted it; an explicit effective time is preserved.

## Atomic writes and replay

The service snapshots scope revision/model, runs providers and related-memory
reads, validates every candidate/relation against source evidence and
allowlisted IDs, then enters `repo.mutation(scope_id, expected_revision)`. The
transaction writes the interaction, immutable memory rows, lifecycle events,
and final decisions together. Supersession stages the replacement as disputed,
points the old row at it, and activates the replacement; this satisfies both
the immediate composite foreign key and one-active-version index. Reinforcement
uses the policy confidence update and the repository's once-per-interaction
event guard; count increment remains a repository concern.

Committed requests require an idempotency key. The request hash covers the
normalized original input and excludes the key and generated timestamps. A
same-key/same-input replay returns the stored response without another
mutation; a different input returns `idempotency_conflict`. A stale revision
rebuilds the provider plan once against a fresh current snapshot, then returns
`revision_conflict` if the second commit is stale. In-flight rows are reported
as `interaction_in_progress`.

Preview requests still validate the full graph and return candidates,
decisions, and timings, but never open a mutation transaction or write an
interaction, revision, memory, or event. Credential candidates are redacted in
the response trace when policy marks them sensitive.

`get_interaction(scope_id=..., interaction_id=...)` always applies the scope
predicate and reconstructs candidates, decisions, memory IDs, and trace from
the stored interaction payload.

Focused coverage lives in `tests/unit/test_providers.py` and
`tests/integration/test_ingestion.py`; the integration tests use temporary
scopes and leave the authored public demo scope untouched.
