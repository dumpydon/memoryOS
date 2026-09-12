# T2 policy handoff

`memoryos.domain.policies` is a pure boundary between model proposals and
persistence. It performs no I/O, does not mutate Pydantic objects, and never
turns an unsupported proposal into a write. The current policy identifier is
`memoryos-v2`.

## Ingestion calls

Validate extracted candidates before relation assessment or persistence:

```python
validate_candidate(
    candidate: object,
    source_text: str,
    *,
    seen_candidate_ids: Collection[str] = (),
) -> CandidateValidation

validate_candidates(
    candidates: Iterable[object],
    source_text: str,
) -> CandidateBatchValidation
```

`CandidateValidation.action` is a `PolicyAction`; accepted candidates have
`decision_type=created`. `CandidateBatchValidation.accepted` contains only the
first occurrence of an exact normalized proposition. A repeated proposition in
one interaction becomes `rejected/duplicate_candidate`, so it cannot
reinforce itself. A candidate must have importance at least `0.30`, confidence
at least `0.60`, `worth_remembering=True`, and evidence that is a
case-folded, whitespace-normalized substring of the source text. Filler and
credential/secret material with source-supported evidence are `skipped`.
Unsupported objects, invalid evidence, duplicate IDs, and invalid timestamps
are `rejected`.

For a relation assessment, pass only the current candidate batch and the
allowlisted memory snapshot:

```python
validate_relation(
    assessment: object,
    candidates: Mapping[str, CandidateMemory] | Iterable[CandidateMemory],
    related_memories: Mapping[UUID, MemoryRecord] | Iterable[MemoryRecord],
    source_text: str,
    *,
    interaction_id: UUID | None = None,
    prior_interaction_ids: Collection[UUID] = (),
    used_candidate_ids: Collection[str] = (),
) -> PolicyAction
```

The helper rejects candidate IDs, related memory IDs, relation types, and
evidence that are not in the supplied allowlist/source. `new` creates only an
accepted candidate; `skip` is a model skip; `dispute` preserves both records;
`reinforce` and `supersede` are guarded actions. A `PolicyAction` can be
converted directly to the response DTO with `action.to_decision()`.

Reinforcement uses:

```python
validate_reinforcement(
    candidate: object,
    existing_memory: object,
    *,
    interaction_id: UUID | None,
    prior_interaction_ids: Collection[UUID] = (),
    trigger: str = "ingestion",
    used_candidate_ids: Collection[str] = (),
    relation_confidence: float | None = None,
) -> PolicyAction
reinforced_confidence(existing_confidence: float, incoming_confidence: float) -> float
```

The current interaction must be new and the trigger must be `ingestion`; a
recall read cannot create reinforcement. Exact normalized content is the fast
path. A paraphrase is accepted only for the same memory type and the same
non-empty subject/context/attribute keys, with a relation confidence of at
least `0.85` and source-supported evidence. Persistence increments
`reinforcement_count` and records the interaction event; the policy helper
only returns the updated confidence. The update is
`min(.95, old + .05 * incoming * (1 - old))`, while a legacy confidence above
`.95` is never reduced.

Supersession is narrower than disagreement. It requires relation confidence
at least `.85`, matching non-empty subject/context/attribute/type keys, an
explicit change/correction marker in source-supported text, and a candidate
`effective_at` strictly newer than the existing memory. Receipt time alone is
never enough. An older imported candidate is `rejected/stale_effective_time`
so the newer active memory remains active. Missing or ambiguous correction
evidence becomes `disputed`, preserving both records. Similarity alone is not
used to infer agreement or conflict.

## Recall calls

Eligibility and scoring are separate so a score can be inspected without
silently changing the recall snapshot:

```python
is_eligible_for_recall(
    memory: MemoryRecord,
    as_of: datetime,
    *,
    include_disputed: bool = False,
    raw_similarity: float | None = None,
    min_similarity: float = 0.25,
    embedding_model: str | None = None,
    embedding_dimensions: int | None = None,
) -> bool

calculate_recall_score(
    memory: MemoryRecord,
    raw_similarity: float,
    as_of: datetime,
) -> RecallScoreBreakdown

score_memory(memory, raw_similarity, as_of) -> ScoredMemory
rank_recall_candidates(memories, similarities, as_of, *, ...) -> list[ScoredMemory]
```

Eligibility includes active memories, or disputed memories only when explicitly
requested; it excludes `expires_at <= as_of`, future `effective_at`, mismatched
embedding model/dimensions, and normalized similarity below `0.25` by default.
The caller supplies both query embedding model and dimensions when enforcing
cross-model recall. All timestamps must be timezone-aware; policy functions
normalize aware values to UTC and reject naive values.

`calculate_recall_score` preserves clamped raw cosine similarity and returns
the DTO's five factors, weighted contributions, total, days since confirmation,
half-life, and policy ID. The score is a ranking signal, not a probability:

```text
S = clamp(raw_cosine, 0, 1)
I = importance
C = confidence
R = 2 ** (-days_since_confirmation / half_life_for_type)
F = min(1, log1p(reinforcement_count) / log(6))
score = .55*S + .15*I + .10*R + .10*F + .10*C
```

Half-lives are preference `180`, semantic `365`, episodic `30`, and procedural
`180` days. Decay never deletes a memory. `rank_recall_candidates` applies the
relevance floor before importance can rank an irrelevant result, then sorts by
total descending, normalized similarity descending, and UUID ascending. The
returned explanation is short and deterministic; use the numeric DTO fields
for exact arithmetic/UI bars.
