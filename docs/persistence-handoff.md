# Persistence handoff

The synchronous SQLAlchemy boundary is in `memoryos.db`. Repository methods do
not commit, so a worker can keep an interaction, memory version, and event in one
transaction. Provider calls and embedding computation happen before the mutation
context is entered.

## Session and scope mutation

```python
from memoryos.db.repositories import MemoryRepository
from memoryos.db.session import session_scope

with session_scope() as session:
    repo = MemoryRepository(session)
    scope = repo.require_scope(scope_id)
    # Providers run before this block.
    with repo.mutation(scope_id=scope_id, expected_revision=scope.revision) as revision:
        interaction = repo.insert_interaction(
            scope_id=scope_id,
            text=text,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            provenance=source_ref,
            occurred_at=occurred_at,
            mode=mode,
            status=InteractionStatus.PROCESSING,
        )
        memory = repo.insert_memory(
            scope_id=scope_id,
            lineage_id=lineage_id,
            version=1,
            content=content,
            memory_type=memory_type,
            importance=importance,
            confidence=confidence,
            embedding=embedding,
            embedding_model=embedding_model,
        )
        repo.insert_event(
            scope_id=scope_id,
            memory_id=memory.record.id,
            interaction_id=interaction.id,
            event_type=MemoryEventType.CREATED,
            relation=MemoryRelation.NEW,
            reason_code="created",
            reason_summary="Created from validated candidate",
        )
    # session_scope commits here, or rolls the complete batch back on error.
```

`repo.mutation(...)` executes `SELECT ... FOR UPDATE` on the scope, asserts the
caller's expected revision, increments it once, and yields the new revision. A
stale revision raises `ScopeRevisionConflict`; a missing scope raises
`ScopeNotFoundError`. The helper does not call providers and does not commit.

Create one `Engine` and `sessionmaker` for the application lifetime with
`create_db_engine(settings)` and `create_session_factory(settings,
engine=engine)`. Pass that factory to `session_scope(session_factory=factory)`
for request transactions.

## Read interfaces

`repo.get_by_id(scope_id, memory_id)` returns a public `MemoryRecord` or `None`.
`repo.get_stored_by_id(...)` returns `StoredMemory`, which contains the same
record plus `embedding`, `embedding_model`, and `embedding_dimensions` for policy
ranking. Every read includes the scope predicate.

`repo.list_memories(scope_id=..., cursor=None, limit=25,
memory_types=None, statuses=None, search=None)` returns
`MemoryListResponse`. The cursor is opaque and ordered by `created_at DESC, id
DESC`.

`repo.get_history(scope_id=..., memory_id=...)` returns
`MemoryHistoryResponse` with every version in the lineage and every event for
those versions. It returns `None` for a memory outside the scope or an unknown
memory.

`repo.list_active_for_recall(request, as_of=..., query_embedding=...,
embedding_model=...)` returns all eligible `RecallCandidate` rows by default.
Eligibility is scoped by `scope_id`, mode/model, memory type, active/disputed
status, `effective_at`, and `expires_at`. If a query vector is supplied, the
database computes exact pgvector cosine similarity and returns `raw_similarity`.
Pass `limit` only when a worker intentionally wants a bounded candidate set; the
request's final recall limit belongs to the ranking worker.

`repo.related_candidates(scope_id=..., attribute_key=..., context_key=...,
query_embedding=..., embedding_model=..., limit=...)` returns
`RelatedCandidate` rows. Each row indicates `attribute_match` and
`context_match`; with a vector it also carries the exact `raw_similarity`. Rows
are ordered by matching attribute/context and then cosine score.

## Write primitives

`insert_interaction(...)` is idempotent for `(scope_id, idempotency_key)`. The
same request hash returns the existing `InteractionResult`; a different hash
raises `IdempotencyConflict`. Preview interactions may omit an idempotency key;
the database rejects a non-preview interaction without one.

`insert_memory(...)` creates one immutable version. `content`, embedding, and
identity fields are never edited by the repository. `set_memory_state(...)`
changes lifecycle fields only. `insert_memory_version(...)` is an alias for
creating another version in an existing lineage.

`reinforce_memory(...)` increments `reinforcement_count`, updates
`last_confirmed_at`, and writes a `reinforced` event. A partial unique index and a
repository precheck guarantee at most one reinforcement for a memory and
interaction pair. `insert_event(...)` writes created/superseded/disputed/
forgotten/resolved/expired events and accepts JSON `before`/`after` evidence.

All identifiers in lifecycle and event foreign keys use `(scope_id, id)`
composite references. A memory or interaction from a different scope therefore
cannot be linked accidentally at the database level.

## Schema and verification

Apply the real migration from `apps/api` with:

```sh
uv run alembic upgrade head
uv run pytest -q tests/integration/test_persistence.py
```

The fixed demo scope is
`00000000-0000-0000-0000-000000000001` and the private/live scope is
`00000000-0000-0000-0000-000000000002`. Demo vectors use
`demo-fixture-v1`; live vectors use `text-embedding-3-small` by default. The
database never broadens a query across scopes; public/demo filtering remains a
transport concern.
