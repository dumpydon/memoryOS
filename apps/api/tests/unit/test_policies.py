from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from memoryos.contracts.ingestion import AdmissionSignals, CandidateMemory, RelationAssessment
from memoryos.contracts.memory import MemoryRecord
from memoryos.domain.enums import IngestDecisionType, MemoryRelation, MemoryStatus, MemoryType
from memoryos.domain.policies import (
    DEFAULT_MIN_SIMILARITY,
    MAX_REINFORCED_CONFIDENCE,
    TYPE_HALF_LIVES_DAYS,
    calculate_recall_score,
    is_eligible_for_recall,
    meets_relevance_floor,
    rank_recall_candidates,
    reinforced_confidence,
    validate_candidate,
    validate_candidates,
    validate_consolidation,
    validate_reinforcement,
    validate_relation,
)

AS_OF = datetime(2026, 1, 31, 12, 0, tzinfo=UTC)
SCOPE_ID = UUID("00000000-0000-0000-0000-000000000001")
MEMORY_ID = UUID("00000000-0000-0000-0000-000000000010")
INTERACTION_ID = UUID("00000000-0000-0000-0000-000000000020")


def candidate(
    *,
    candidate_id: str = "c1",
    content: str = "Alex prefers tea",
    subject: str | None = "alex",
    context_key: str | None = "work",
    attribute_key: str | None = "drink",
    evidence_excerpt: str = "Alex prefers tea",
    importance: float = 0.8,
    confidence: float = 0.8,
    effective_at: datetime | None = None,
    worth_remembering: bool = True,
) -> CandidateMemory:
    return CandidateMemory(
        candidate_id=candidate_id,
        content=content,
        memory_type=MemoryType.PREFERENCE,
        subject=subject,
        context_key=context_key,
        attribute_key=attribute_key,
        importance=importance,
        confidence=confidence,
        evidence_excerpt=evidence_excerpt,
        effective_at=effective_at,
        worth_remembering=worth_remembering,
        admission=AdmissionSignals(
            durability="lasting",
            future_value="personalization",
            specificity="specific",
            evidence_source="user",
            content_kind="information",
        ),
    )


def memory(
    *,
    memory_id: UUID = MEMORY_ID,
    content: str = "Alex prefers tea",
    subject: str | None = "alex",
    context_key: str | None = "work",
    attribute_key: str | None = "drink",
    status: MemoryStatus = MemoryStatus.ACTIVE,
    memory_type: MemoryType = MemoryType.PREFERENCE,
    last_confirmed_at: datetime = AS_OF,
    effective_at: datetime = AS_OF - timedelta(days=1),
    expires_at: datetime | None = None,
    importance: float = 0.8,
    confidence: float = 0.8,
    reinforcement_count: int = 0,
    embedding_model: str = "demo-fixture-v1",
    embedding_dimensions: int = 3,
) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        scope_id=SCOPE_ID,
        lineage_id=memory_id,
        version=1,
        content=content,
        memory_type=memory_type,
        status=status,
        subject=subject,
        context_key=context_key,
        attribute_key=attribute_key,
        importance=importance,
        confidence=confidence,
        reinforcement_count=reinforcement_count,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        created_at=AS_OF - timedelta(days=2),
        effective_at=effective_at,
        last_confirmed_at=last_confirmed_at,
        expires_at=expires_at,
    )


def assessment(
    *,
    candidate_id: str = "c1",
    related_memory_id: UUID | None = MEMORY_ID,
    relation: MemoryRelation = MemoryRelation.REINFORCE,
    confidence: float = 0.9,
    evidence_excerpt: str = "Alex prefers tea",
    value_comparison: str | None = None,
    replacement_evidence: str | None = None,
) -> RelationAssessment:
    return RelationAssessment(
        candidate_id=candidate_id,
        related_memory_id=related_memory_id,
        relation=relation,
        confidence=confidence,
        evidence_excerpt=evidence_excerpt,
        reason_code="test",
        reason_summary="test relation",
        value_comparison=value_comparison
        or ("equivalent" if relation is MemoryRelation.REINFORCE else "incompatible"),
        replacement_evidence=replacement_evidence,
    )


def test_score_uses_type_half_life_and_does_not_delete_memory() -> None:
    before = memory(last_confirmed_at=AS_OF)
    after = memory(
        last_confirmed_at=AS_OF - timedelta(days=TYPE_HALF_LIVES_DAYS[MemoryType.PREFERENCE])
    )

    at_confirmation = calculate_recall_score(before, 0.5, AS_OF)
    one_half_life_later = calculate_recall_score(after, 0.5, AS_OF)

    assert at_confirmation.recency == 1.0
    assert one_half_life_later.recency == 0.5
    assert one_half_life_later.days_since_confirmation == 180
    assert after.status is MemoryStatus.ACTIVE


def test_score_saturates_reinforcement_and_contributions_sum() -> None:
    score = calculate_recall_score(
        memory(reinforcement_count=100),
        raw_similarity=-0.1,
        as_of=AS_OF,
    )

    assert score.raw_similarity == -0.1
    assert score.similarity == 0
    assert score.reinforcement == 1.0
    contributions = (
        score.weighted_similarity,
        score.weighted_importance,
        score.weighted_recency,
        score.weighted_reinforcement,
        score.weighted_confidence,
    )
    assert score.total == sum(contributions)
    assert "Weak semantic match" in __import__(
        "memoryos.domain.policies", fromlist=["score_explanation"]
    ).score_explanation(score)


def test_relevance_floor_happens_before_importance() -> None:
    assert meets_relevance_floor(DEFAULT_MIN_SIMILARITY)
    assert not meets_relevance_floor(DEFAULT_MIN_SIMILARITY - 0.01)
    ranked = rank_recall_candidates(
        [memory(importance=1.0)],
        {MEMORY_ID: 0.2},
        AS_OF,
    )
    assert ranked == []


def test_recall_eligibility_filters_expiry_future_status_and_model() -> None:
    assert is_eligible_for_recall(memory(), AS_OF)
    assert not is_eligible_for_recall(
        memory(expires_at=AS_OF),
        AS_OF,
    )
    assert not is_eligible_for_recall(
        memory(effective_at=AS_OF + timedelta(seconds=1)),
        AS_OF,
    )
    assert not is_eligible_for_recall(
        memory(status=MemoryStatus.DISPUTED),
        AS_OF,
    )
    assert is_eligible_for_recall(
        memory(status=MemoryStatus.DISPUTED),
        AS_OF,
        include_disputed=True,
    )
    assert not is_eligible_for_recall(
        memory(),
        AS_OF,
        embedding_model="other-model",
        embedding_dimensions=3,
    )


def test_candidate_requires_source_evidence_and_thresholds() -> None:
    unsupported = validate_candidate(
        candidate(evidence_excerpt="not in source"),
        "Alex prefers tea",
    )
    assert unsupported.action.decision_type is IngestDecisionType.REJECTED
    assert unsupported.action.reason_code == "unsupported_evidence"

    low_importance = validate_candidate(
        candidate(importance=0.29),
        "Alex prefers tea",
    )
    assert low_importance.action.decision_type is IngestDecisionType.SKIPPED
    assert low_importance.action.reason_code == "low_importance"


def test_filler_and_secret_candidates_are_skipped_only_with_supported_evidence() -> None:
    filler = validate_candidate(
        candidate(content="Thanks", evidence_excerpt="Thanks"),
        "Thanks",
    )
    secret = validate_candidate(
        candidate(content="The API key is hunter2", evidence_excerpt="API key is hunter2"),
        "The API key is hunter2",
    )
    assert filler.action.decision_type is IngestDecisionType.SKIPPED
    assert filler.action.reason_code == "filler_content"
    assert secret.action.decision_type is IngestDecisionType.SKIPPED
    assert secret.action.reason_code == "sensitive_secret"


def test_candidates_cannot_reinforce_themselves_within_one_request() -> None:
    batch = validate_candidates(
        [
            candidate(candidate_id="first"),
            candidate(candidate_id="second"),
        ],
        "Alex prefers tea",
    )
    assert [item.action.decision_type for item in batch.validations] == [
        IngestDecisionType.CREATED,
        IngestDecisionType.REJECTED,
    ]
    assert batch.validations[1].action.reason_code == "duplicate_candidate"


def test_reinforcement_requires_same_context_distinct_ingestion() -> None:
    existing = memory(confidence=0.8, reinforcement_count=2)
    accepted = validate_reinforcement(
        candidate(),
        existing,
        interaction_id=INTERACTION_ID,
    )
    assert accepted.decision_type is IngestDecisionType.REINFORCED
    assert accepted.confidence == reinforced_confidence(0.8, 0.8)
    assert existing.reinforcement_count == 2

    duplicate_interaction = validate_reinforcement(
        candidate(),
        existing,
        interaction_id=INTERACTION_ID,
        prior_interaction_ids={INTERACTION_ID},
    )
    retrieval = validate_reinforcement(
        candidate(),
        existing,
        interaction_id=UUID("00000000-0000-0000-0000-000000000021"),
        trigger="recall",
    )
    distinct_context = validate_reinforcement(
        candidate(context_key="home"),
        existing,
        interaction_id=UUID("00000000-0000-0000-0000-000000000022"),
    )
    assert duplicate_interaction.decision_type is IngestDecisionType.REJECTED
    assert retrieval.decision_type is IngestDecisionType.REJECTED
    assert distinct_context.decision_type is IngestDecisionType.REJECTED


def test_reinforcement_does_not_reduce_legacy_confidence_above_cap() -> None:
    assert reinforced_confidence(0.96, 0.1) == 0.96
    assert reinforced_confidence(0.8, 1.0) <= MAX_REINFORCED_CONFIDENCE


def test_high_confidence_relation_can_reinforce_semantic_paraphrase() -> None:
    result = validate_relation(
        assessment(
            relation=MemoryRelation.REINFORCE,
            confidence=0.9,
            evidence_excerpt="Alex likes tea",
        ),
        {
            "c1": candidate(
                content="Alex likes tea",
                evidence_excerpt="Alex likes tea",
            )
        },
        {MEMORY_ID: memory()},
        "Alex likes tea",
        interaction_id=INTERACTION_ID,
    )
    low_confidence = validate_relation(
        assessment(
            relation=MemoryRelation.REINFORCE,
            confidence=0.84,
            evidence_excerpt="Alex likes tea",
        ),
        {
            "c1": candidate(
                content="Alex likes tea",
                evidence_excerpt="Alex likes tea",
            )
        },
        {MEMORY_ID: memory()},
        "Alex likes tea",
        interaction_id=UUID("00000000-0000-0000-0000-000000000021"),
    )
    assert result.decision_type is IngestDecisionType.REINFORCED
    assert low_confidence.decision_type is IngestDecisionType.REJECTED


def test_reported_learning_paraphrase_allows_compatible_attribute_key() -> None:
    existing = memory(
        content="The user prefers concise explanations when learning algorithms.",
        subject="user",
        context_key="learning_algorithms",
        attribute_key="explanation_length",
        confidence=0.99,
    )
    source = (
        "I still strongly prefer concise explanations when learning algorithms. "
        "Please keep explanations short and focused."
    )
    incoming = candidate(
        content="The user strongly prefers short, focused explanations when learning algorithms.",
        subject="user",
        context_key="learning_algorithms",
        attribute_key="explanation_style",
        evidence_excerpt=source,
        confidence=0.99,
    )
    result = validate_relation(
        assessment(
            relation=MemoryRelation.REINFORCE,
            confidence=0.95,
            evidence_excerpt=source,
        ),
        {incoming.candidate_id: incoming},
        {MEMORY_ID: existing},
        source,
        interaction_id=INTERACTION_ID,
    )
    assert result.decision_type is IngestDecisionType.REINFORCED
    assert result.reason_code == "same_context_paraphrase_new_interaction"
    assert result.memory_id == MEMORY_ID


def test_python_example_paraphrase_allows_compatible_attribute_key() -> None:
    existing = memory(
        content="Alex prefers Python examples.",
        context_key="interviews",
        attribute_key="example_language",
    )
    source = "Please continue showing code examples in Python."
    incoming = candidate(
        content="Alex wants code examples in Python.",
        context_key="interviews",
        attribute_key="example_format",
        evidence_excerpt=source,
    )
    result = validate_relation(
        assessment(
            relation=MemoryRelation.REINFORCE,
            confidence=0.91,
            evidence_excerpt=source,
        ),
        {incoming.candidate_id: incoming},
        {MEMORY_ID: existing},
        source,
        interaction_id=INTERACTION_ID,
    )
    assert result.decision_type is IngestDecisionType.REINFORCED


def test_reinforcement_rejects_different_context_even_when_values_overlap() -> None:
    existing = memory(
        content="Alex prefers Python for interviews.",
        context_key="interviews",
        attribute_key="example_language",
    )
    source = "Alex uses TypeScript at work."
    incoming = candidate(
        content="Alex uses TypeScript at work.",
        context_key="work",
        attribute_key="example_language",
        evidence_excerpt=source,
    )
    result = validate_relation(
        assessment(
            relation=MemoryRelation.REINFORCE,
            confidence=0.99,
            evidence_excerpt=source,
        ),
        {incoming.candidate_id: incoming},
        {MEMORY_ID: existing},
        source,
        interaction_id=INTERACTION_ID,
    )
    assert result.decision_type is IngestDecisionType.CREATED
    assert result.reason_code == "contextual_coexistence"


def test_reinforcement_rejects_negation_and_replacement_language() -> None:
    existing = memory(
        content="Alex prefers concise answers.",
        context_key="responses",
        attribute_key="answer_length",
    )
    replacement_source = "From now on use detailed answers instead of concise ones."
    replacement = candidate(
        content="Alex prefers detailed answers.",
        context_key="responses",
        attribute_key="answer_length",
        evidence_excerpt=replacement_source,
    )
    replacement_result = validate_relation(
        assessment(
            relation=MemoryRelation.REINFORCE,
            confidence=0.99,
            evidence_excerpt=replacement_source,
        ),
        {replacement.candidate_id: replacement},
        {MEMORY_ID: existing},
        replacement_source,
        interaction_id=INTERACTION_ID,
    )
    negation_source = "Alex does not prefer concise answers."
    negation = candidate(
        content="Alex does not prefer concise answers.",
        context_key="responses",
        attribute_key="answer_length",
        evidence_excerpt=negation_source,
    )
    negation_result = validate_relation(
        assessment(
            relation=MemoryRelation.REINFORCE,
            confidence=0.99,
            evidence_excerpt=negation_source,
        ),
        {negation.candidate_id: negation},
        {MEMORY_ID: existing},
        negation_source,
        interaction_id=UUID("00000000-0000-0000-0000-000000000021"),
    )
    assert replacement_result.reason_code == "reinforcement_change_language"
    assert negation_result.reason_code == "reinforcement_change_language"


def test_reinforcement_rejects_weak_semantic_overlap() -> None:
    existing = memory(
        content="Alex prefers short answers.",
        context_key="interviews",
        attribute_key="answer_length",
    )
    source = "Alex's interview is short tomorrow."
    incoming = candidate(
        content="Alex's interview is short tomorrow.",
        context_key="interviews",
        attribute_key="answer_length",
        evidence_excerpt=source,
    )
    result = validate_relation(
        assessment(
            relation=MemoryRelation.REINFORCE,
            confidence=0.99,
            evidence_excerpt=source,
        ),
        {incoming.candidate_id: incoming},
        {MEMORY_ID: existing},
        source,
        interaction_id=INTERACTION_ID,
    )
    assert result.decision_type is IngestDecisionType.REJECTED
    assert result.reason_code == "semantic_proposition_mismatch"


def test_relation_rejects_spoofed_ids_and_evidence() -> None:
    unknown_candidate = validate_relation(
        assessment(candidate_id="spoof", evidence_excerpt="Alex prefers tea"),
        {"c1": candidate()},
        {MEMORY_ID: memory()},
        "Alex prefers tea",
    )
    unknown_memory = validate_relation(
        assessment(related_memory_id=UUID("00000000-0000-0000-0000-000000000099")),
        {"c1": candidate()},
        {MEMORY_ID: memory()},
        "Alex prefers tea",
        interaction_id=INTERACTION_ID,
    )
    fake_evidence = validate_relation(
        assessment(evidence_excerpt="not in source"),
        {"c1": candidate()},
        {MEMORY_ID: memory()},
        "Alex prefers tea",
    )
    assert unknown_candidate.reason_code == "unknown_candidate_id"
    assert unknown_memory.reason_code == "unknown_related_memory_id"
    assert fake_evidence.reason_code == "unsupported_evidence"


def test_explicit_newer_correction_can_supersede() -> None:
    existing = memory(effective_at=datetime(2026, 1, 10, tzinfo=UTC))
    newer = candidate(
        content="Alex prefers coffee",
        evidence_excerpt="now prefers coffee",
        effective_at=datetime(2026, 1, 11, tzinfo=UTC),
    )
    result = validate_relation(
        assessment(
            relation=MemoryRelation.SUPERSEDE,
            confidence=0.9,
            evidence_excerpt="now prefers coffee",
            replacement_evidence="Correction: Alex now prefers coffee instead of tea.",
        ),
        {"c1": newer},
        {MEMORY_ID: existing},
        "Correction: Alex now prefers coffee instead of tea.",
    )
    assert result.decision_type is IngestDecisionType.SUPERSEDED
    assert result.related_memory_id == MEMORY_ID


def test_model_invented_change_marker_cannot_prove_supersession() -> None:
    result = validate_relation(
        assessment(
            relation=MemoryRelation.SUPERSEDE,
            confidence=0.95,
            evidence_excerpt="Alex prefers coffee",
        ),
        {
            "c1": candidate(
                content="Alex now prefers coffee",
                evidence_excerpt="Alex prefers coffee",
                effective_at=datetime(2026, 1, 11, tzinfo=UTC),
            )
        },
        {MEMORY_ID: memory(effective_at=datetime(2026, 1, 10, tzinfo=UTC))},
        "Alex prefers coffee.",
    )
    assert result.decision_type is IngestDecisionType.DISPUTED


def test_same_content_supersede_uses_reinforcement_guards() -> None:
    result = validate_relation(
        assessment(
            relation=MemoryRelation.SUPERSEDE,
            confidence=0.95,
            evidence_excerpt="Alex prefers tea",
        ),
        {"c1": candidate()},
        {MEMORY_ID: memory()},
        "Alex prefers tea",
    )
    assert result.decision_type is IngestDecisionType.REJECTED
    assert result.reason_code == "interaction_id_required"


def test_dispute_requires_valid_same_identity_active_candidate() -> None:
    secret = validate_relation(
        assessment(relation=MemoryRelation.DISPUTE, evidence_excerpt="password is hunter2"),
        {
            "c1": candidate(
                content="Alex password is hunter2",
                evidence_excerpt="password is hunter2",
            )
        },
        {MEMORY_ID: memory()},
        "Alex password is hunter2",
    )
    unrelated = validate_relation(
        assessment(relation=MemoryRelation.DISPUTE, evidence_excerpt="Alex prefers coffee"),
        {
            "c1": candidate(
                content="Alex prefers coffee",
                evidence_excerpt="Alex prefers coffee",
                context_key="home",
            )
        },
        {MEMORY_ID: memory()},
        "Alex prefers coffee",
    )
    assert secret.decision_type is IngestDecisionType.SKIPPED
    assert unrelated.decision_type is IngestDecisionType.CREATED
    assert unrelated.reason_code == "contextual_coexistence"


def test_naive_timestamps_are_rejected_by_scoring() -> None:
    with pytest.raises(ValueError, match="must include a timezone"):
        calculate_recall_score(memory(), 0.5, datetime(2026, 1, 31, 12, 0))


def test_old_imported_correction_and_ambiguous_change_preserve_both() -> None:
    existing = memory(effective_at=datetime(2026, 1, 10, tzinfo=UTC))
    old = candidate(
        content="Alex prefers coffee",
        evidence_excerpt="now prefers coffee",
        effective_at=datetime(2026, 1, 9, tzinfo=UTC),
    )
    stale = validate_relation(
        assessment(
            relation=MemoryRelation.SUPERSEDE,
            confidence=0.95,
            evidence_excerpt="now prefers coffee",
            replacement_evidence="Imported correction: Alex now prefers coffee instead of tea.",
        ),
        {"c1": old},
        {MEMORY_ID: existing},
        "Imported correction: Alex now prefers coffee instead of tea.",
    )
    ambiguous = validate_relation(
        assessment(
            relation=MemoryRelation.SUPERSEDE,
            confidence=0.95,
            evidence_excerpt="Alex prefers coffee",
        ),
        {
            "c1": candidate(
                content="Alex prefers coffee",
                evidence_excerpt="Alex prefers coffee",
                effective_at=datetime(2026, 1, 11, tzinfo=UTC),
            )
        },
        {MEMORY_ID: existing},
        "Alex prefers coffee.",
    )
    assert stale.decision_type is IngestDecisionType.REJECTED
    assert stale.reason_code == "stale_effective_time"
    assert existing.status is MemoryStatus.ACTIVE
    assert ambiguous.decision_type is IngestDecisionType.DISPUTED


def test_same_similarity_ties_are_broken_by_similarity_then_uuid() -> None:
    first_id = UUID("00000000-0000-0000-0000-000000000011")
    second_id = UUID("00000000-0000-0000-0000-000000000012")
    first = memory(memory_id=first_id, content="one", subject="one", attribute_key="fact")
    second = memory(memory_id=second_id, content="two", subject="two", attribute_key="fact")
    ranked = rank_recall_candidates([second, first], {first_id: 0.5, second_id: 0.5}, AS_OF)
    assert [item.memory.id for item in ranked] == [first_id, second_id]


@pytest.mark.parametrize(
    "memory_type,future_value,content",
    [
        (MemoryType.PREFERENCE, "personalization", "I prefer concise code explanations."),
        (MemoryType.SEMANTIC, "reference", "Atlas stores event timestamps in UTC."),
        (
            MemoryType.PROCEDURAL,
            "procedure",
            "To run schema migrations, use uv run alembic upgrade head.",
        ),
        (
            MemoryType.EPISODIC,
            "significant_event",
            "Atlas launched its public memory API at the conference.",
        ),
    ],
)
def test_admission_accepts_specific_supported_information(memory_type, future_value, content):
    item = candidate(content=content, evidence_excerpt=content).model_copy(
        update={
            "memory_type": memory_type,
            "admission": AdmissionSignals.model_validate(
                {
                    "durability": "lasting",
                    "future_value": future_value,
                    "specificity": "specific",
                    "evidence_source": "user",
                    "content_kind": "information",
                }
            ),
        }
    )
    result = validate_candidate(item, content)
    assert result.accepted
    assert result.action.reason_code == f"admitted_{memory_type.value}"


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"durability": "transient"}, "transient_information"),
        ({"durability": "uncertain"}, "uncertain_durability"),
        ({"future_value": "none"}, "no_future_value"),
        ({"specificity": "vague"}, "vague_information"),
        ({"evidence_source": "inferred"}, "unsupported_inference"),
        ({"evidence_source": "assistant"}, "assistant_generated"),
        ({"content_kind": "one_off_request"}, "temporary_request"),
    ],
)
def test_admission_rejects_weak_signals_even_with_high_scores(updates, reason):
    item = candidate(confidence=0.99, importance=0.99)
    item = item.model_copy(update={"admission": item.admission.model_copy(update=updates)})
    result = validate_candidate(item, "Alex prefers tea")
    assert not result.accepted
    assert result.action.reason_code == reason


def test_admission_fails_closed_for_missing_signals_and_weak_confidence():
    item = candidate().model_copy(update={"admission": None})
    assert (
        validate_candidate(item, "Alex prefers tea").action.reason_code
        == "admission_signals_missing"
    )
    assert (
        validate_candidate(candidate(confidence=0.79), "Alex prefers tea").action.reason_code
        == "low_confidence"
    )


@pytest.mark.parametrize(
    "source,replacement,confidence,comparison,status",
    [
        (
            "Alex currently prefers coffee.",
            "Alex currently prefers coffee.",
            0.99,
            "incompatible",
            MemoryStatus.ACTIVE,
        ),
        (
            "From now on use Cursor. Alex prefers coffee.",
            "From now on use Cursor. Alex prefers coffee.",
            0.99,
            "incompatible",
            MemoryStatus.ACTIVE,
        ),
        (
            "Maybe Alex switched from tea to coffee.",
            "Maybe Alex switched from tea to coffee.",
            0.99,
            "incompatible",
            MemoryStatus.ACTIVE,
        ),
        (
            "Alex did not switch from tea to coffee.",
            "Alex did not switch from tea to coffee.",
            0.99,
            "incompatible",
            MemoryStatus.ACTIVE,
        ),
        (
            "Correction: Alex prefers coffee instead of tea.",
            "Correction: Alex prefers coffee instead of tea.",
            0.89,
            "incompatible",
            MemoryStatus.ACTIVE,
        ),
        (
            "Correction: Alex prefers coffee instead of tea.",
            "Correction: Alex prefers coffee instead of tea.",
            0.99,
            "uncertain",
            MemoryStatus.ACTIVE,
        ),
        (
            "Correction: Alex prefers coffee instead of tea.",
            "Correction: Alex prefers coffee instead of tea.",
            0.99,
            "incompatible",
            MemoryStatus.DISPUTED,
        ),
        (
            "Alex prefers coffee.",
            "Correction: Alex prefers coffee instead of tea.",
            0.99,
            "incompatible",
            MemoryStatus.ACTIVE,
        ),
    ],
)
def test_supersession_needs_strong_claim_bound_replacement_evidence(
    source, replacement, confidence, comparison, status
):
    incoming = candidate(content="Alex prefers coffee", evidence_excerpt=source, effective_at=AS_OF)
    existing = memory(status=status, effective_at=AS_OF - timedelta(days=1))
    result = validate_relation(
        assessment(
            relation=MemoryRelation.SUPERSEDE,
            confidence=confidence,
            evidence_excerpt=source,
            replacement_evidence=replacement,
            value_comparison=comparison,
        ),
        {"c1": incoming},
        {MEMORY_ID: existing},
        source,
        interaction_id=INTERACTION_ID,
    )
    assert result.decision_type is IngestDecisionType.DISPUTED
    assert existing.status is status


def test_shared_attribute_words_cannot_prove_equivalent_editor_values():
    source = "Alex's primary editor is Cursor."
    incoming = candidate(content=source, evidence_excerpt=source, attribute_key="primary_editor")
    existing = memory(
        content="Alex's primary editor is VS Code.", attribute_key="editor_preference"
    )
    result = validate_relation(
        assessment(evidence_excerpt=source, value_comparison="equivalent"),
        {"c1": incoming},
        {MEMORY_ID: existing},
        source,
        interaction_id=INTERACTION_ID,
    )
    assert result.decision_type is IngestDecisionType.REJECTED
    assert result.reason_code == "semantic_proposition_mismatch"


def test_new_proposal_cannot_duplicate_a_supported_paraphrase():
    source = "Alex still prefers short explanations."
    incoming = candidate(content=source, evidence_excerpt=source, attribute_key="explanation_style")
    existing = memory(
        content="Alex prefers concise explanations.", attribute_key="explanation_length"
    )
    result = validate_relation(
        assessment(
            relation=MemoryRelation.NEW,
            related_memory_id=None,
            evidence_excerpt=source,
            value_comparison="equivalent",
        ),
        {"c1": incoming},
        {MEMORY_ID: existing},
        source,
        interaction_id=INTERACTION_ID,
    )
    assert result.decision_type is IngestDecisionType.REINFORCED


def test_repeated_disputed_value_cannot_create_another_conflict():
    source = "Alex prefers coffee"
    incoming = candidate(content=source, evidence_excerpt=source)
    disputed_id = UUID("00000000-0000-0000-0000-000000000012")
    result = validate_relation(
        assessment(relation=MemoryRelation.DISPUTE, evidence_excerpt=source),
        {"c1": incoming},
        {
            MEMORY_ID: memory(status=MemoryStatus.DISPUTED),
            disputed_id: memory(
                memory_id=disputed_id, content=source, status=MemoryStatus.DISPUTED
            ),
        },
        source,
        interaction_id=INTERACTION_ID,
    )
    assert result.decision_type is IngestDecisionType.SKIPPED
    assert result.reason_code == "pending_conflict_already_represented"


def test_supersession_requires_a_present_subject_not_two_missing_values():
    source = "Correction: now prefer coffee instead of tea."
    incoming = candidate(
        content="Prefer coffee", subject=None, evidence_excerpt=source, effective_at=AS_OF
    )
    existing = memory(content="Prefer tea", subject=None)
    result = validate_relation(
        assessment(
            relation=MemoryRelation.SUPERSEDE, evidence_excerpt=source, replacement_evidence=source
        ),
        {"c1": incoming},
        {MEMORY_ID: existing},
        source,
    )
    assert result.decision_type is IngestDecisionType.DISPUTED
    assert result.reason_code == "ambiguous_supersede_identity"


def consolidation_sources():
    left = memory(
        content="Alex prefers concise algorithm explanations.",
        context_key="algorithms",
        attribute_key="explanation_length",
        confidence=0.95,
    )
    right = memory(
        memory_id=UUID("00000000-0000-0000-0000-000000000013"),
        content="Alex likes short, focused DSA explanations.",
        context_key="algorithms",
        attribute_key="explanation_style",
        confidence=0.95,
    )
    incoming = candidate(
        content="Alex prefers short, focused algorithm explanations.",
        context_key="algorithms",
        attribute_key="explanation_style",
        confidence=0.95,
    )
    return left, right, incoming


def test_consolidation_selects_a_complete_verbatim_source():
    left, right, incoming = consolidation_sources()
    result = validate_consolidation([left, right], candidate=incoming, as_of=AS_OF)
    assert result.plan is not None
    assert result.plan.canonical.content == right.content
    assert {m.id for m in result.plan.sources} == {left.id, right.id}


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"context_key": "system_design"}, "contexts differ"),
        ({"content": "Alex uses FastAPI for MemoryOS."}, "distinct or uncertain knowledge"),
        (
            {"content": "Alex prefers detailed algorithm explanations."},
            "distinct or uncertain knowledge",
        ),
        ({"content": "Alex prefers concise explanations without theory."}, "human judgment"),
        ({"status": MemoryStatus.DISPUTED}, "only active"),
        ({"status": MemoryStatus.FORGOTTEN}, "only active"),
        ({"confidence": 0.85}, "not strong enough"),
    ],
)
def test_consolidation_refuses_unsafe_or_ambiguous_overlap(updates, reason):
    left, right, incoming = consolidation_sources()
    result = validate_consolidation(
        [left, right.model_copy(update=updates)],
        candidate=incoming,
        as_of=AS_OF,
    )
    assert result.plan is None
    assert reason in result.reason
