"""Pure, versioned MemoryOS domain policies.

The language model proposes candidates and relationships. This module is the
small deterministic boundary that decides whether a proposal is safe to pass
to persistence and how an already stored memory is ranked for recall. It does
not perform I/O, call a model, or mutate a candidate or memory record.
"""

from __future__ import annotations

import math
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, TypeGuard
from uuid import UUID

from memoryos.domain.enums import IngestDecisionType, MemoryRelation, MemoryStatus, MemoryType

if TYPE_CHECKING:
    from memoryos.contracts.ingestion import CandidateMemory, IngestDecision, RelationAssessment
    from memoryos.contracts.memory import MemoryRecord
    from memoryos.contracts.recall import RecallScoreBreakdown

MEMORYOS_POLICY_VERSION: Final[str] = "memoryos-v5"
SCORE_WEIGHTS: Final[dict[str, float]] = {
    "similarity": 0.55,
    "importance": 0.15,
    "recency": 0.10,
    "reinforcement": 0.10,
    "confidence": 0.10,
}
TYPE_HALF_LIVES_DAYS: Final[dict[MemoryType, int]] = {
    MemoryType.PREFERENCE: 180,
    MemoryType.SEMANTIC: 365,
    MemoryType.EPISODIC: 30,
    MemoryType.PROCEDURAL: 180,
}

MIN_IMPORTANCE: Final[float] = 0.40
MIN_CONFIDENCE: Final[float] = 0.80
MAX_REINFORCED_CONFIDENCE: Final[float] = 0.95
REINFORCE_RELATION_CONFIDENCE: Final[float] = 0.85
SUPERSEDE_RELATION_CONFIDENCE: Final[float] = 0.90
DEFAULT_MIN_SIMILARITY: Final[float] = 0.25

_FILLER_RE = re.compile(
    r"^(?:ok(?:ay)?|thanks?(?:\s+you)?|thank\s+you|hello|hi|hey|sure|yes|no|"
    r"got\s+it|sounds\s+good|great|cool|fine|understood|welcome|how\s+are\s+you)[.!?]*$",
    re.IGNORECASE,
)
_SECRET_TERM_RE = re.compile(
    r"\b(?:password|passwd|passcode|api[\s_-]*key|secret(?:\s+key)?|"
    r"access\s+token|refresh\s+token|bearer\s+token|private[\s_-]*key|"
    r"credential(?:s)?)\b",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?:password|passwd|passcode|api[\s_-]*key|secret(?:\s+key)?|"
    r"access\s+token|refresh\s+token|bearer\s+token|private[\s_-]*key|"
    r"credential(?:s)?)\b\s*(?:is|are|=|:)\s*\S+",
    re.IGNORECASE,
)
_EXPLICIT_CHANGE_RE = re.compile(
    r"\b(?:from\s+now\s+on|no\s+longer|instead|"
    r"changed?|updated?|correction|correct(?:ion)?|switch(?:ed)?|"
    r"replace(?:d)?|rather\s+than)\b",
    re.IGNORECASE,
)
_UNCERTAIN_CHANGE_RE = re.compile(
    r"\b(?:if|might|maybe|perhaps|could|would|considering|"
    r"didn't|did\s+not|haven't|have\s+not|"
    r"not\s+(?:switch(?:ed|ing)?|chang(?:e|ed|ing)|replac(?:e|ed|ing)))\b",
    re.IGNORECASE,
)
_REINFORCEMENT_NEGATION_RE = re.compile(
    r"\b(?:not|never|without|no|don't|doesn't|didn't|can't|cannot|won't|wouldn't|"
    r"isn't|aren't|neither|nor)\b",
    re.IGNORECASE,
)
_REINFORCEMENT_REPLACEMENT_RE = re.compile(
    r"\b(?:used\s+to|previously|formerly|no\s+longer|anymore|from\s+now\s+on|"
    r"instead\s+of|rather\s+than|replace(?:d|ment)?|switch(?:ed|ing)?|"
    r"changed?|updated?|correction)\b|"
    r"\bnow\s+(?:prefer|want|use|choose|favor|need)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-z0-9]+")
_PROPOSITION_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "please",
        "that",
        "the",
        "their",
        "this",
        "to",
        "when",
        "while",
        "with",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "they",
        "them",
        "still",
        "strongly",
        "really",
        "very",
        "keep",
        "keeps",
        "continue",
        "continued",
        "show",
        "showing",
        "also",
        "just",
    }
)
_PROPOSITION_PREDICATES: Final[frozenset[str]] = frozenset(
    {
        "prefer",
        "like",
        "want",
        "need",
        "use",
        "choose",
        "favor",
        "enjoy",
        "ask",
        "request",
    }
)
_TOKEN_ALIASES: Final[dict[str, str]] = {
    "dsa": "algorithm",
    "brief": "concise",
    "short": "concise",
    "succinct": "concise",
    "likes": "prefer",
    "liked": "prefer",
    "prefers": "prefer",
    "preferred": "prefer",
    "wants": "want",
    "wanted": "want",
    "favors": "favor",
    "favored": "favor",
    "focused": "focus",
}
_GENERIC_KEY_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "choice",
        "format",
        "language",
        "length",
        "mode",
        "option",
        "preference",
        "setting",
        "state",
        "style",
        "type",
        "value",
    }
)

if TYPE_CHECKING:
    type CandidateLike = CandidateMemory | MemoryRecord


def _is_candidate_memory(value: object) -> TypeGuard[CandidateMemory]:
    from memoryos.contracts.ingestion import CandidateMemory

    return isinstance(value, CandidateMemory)


def _is_memory_record(value: object) -> TypeGuard[MemoryRecord]:
    from memoryos.contracts.memory import MemoryRecord

    return isinstance(value, MemoryRecord)


def _is_relation_assessment(value: object) -> TypeGuard[RelationAssessment]:
    from memoryos.contracts.ingestion import RelationAssessment

    return isinstance(value, RelationAssessment)


@dataclass(frozen=True, slots=True)
class PolicyAction:
    """A small, persistence-ready result from a policy check."""

    decision_type: IngestDecisionType
    reason_code: str
    reason_summary: str
    candidate_id: str | None = None
    memory_id: UUID | None = None
    related_memory_id: UUID | None = None
    confidence: float | None = None
    source_memory_ids: tuple[UUID, ...] = ()
    consolidation_note: str | None = None
    canonical_content: str | None = None

    @property
    def accepted(self) -> bool:
        """Whether this action may be passed to the persistence worker."""

        return self.decision_type in {
            IngestDecisionType.CREATED,
            IngestDecisionType.CONSOLIDATED,
            IngestDecisionType.REINFORCED,
            IngestDecisionType.SUPERSEDED,
            IngestDecisionType.DISPUTED,
        }

    def to_decision(self) -> IngestDecision:
        """Convert this policy result to the public ingestion response shape."""

        from memoryos.contracts.ingestion import IngestDecision

        return IngestDecision(
            decision_type=self.decision_type,
            candidate_id=self.candidate_id,
            memory_id=self.memory_id,
            related_memory_id=self.related_memory_id,
            reason_code=self.reason_code,
            reason_summary=self.reason_summary,
            confidence=self.confidence,
            source_memory_ids=list(self.source_memory_ids),
            consolidation_note=self.consolidation_note,
            canonical_content=self.canonical_content,
        )


@dataclass(frozen=True, slots=True)
class CandidateValidation:
    """Validation result for one model-proposed candidate."""

    action: PolicyAction
    candidate: CandidateMemory | None = None

    @property
    def accepted(self) -> bool:
        return self.action.decision_type is IngestDecisionType.CREATED


@dataclass(frozen=True, slots=True)
class CandidateBatchValidation:
    """Validation and request-local deduplication for extracted candidates."""

    validations: tuple[CandidateValidation, ...]

    @property
    def accepted(self) -> tuple[CandidateMemory, ...]:
        return tuple(
            result.candidate
            for result in self.validations
            if result.accepted and result.candidate is not None
        )


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    """Stable first-wins deduplication result for one extraction request."""

    unique: tuple[CandidateMemory, ...]
    duplicates: tuple[tuple[CandidateMemory, CandidateMemory], ...]


@dataclass(frozen=True, slots=True)
class ScoredMemory:
    """A memory with its explainable score and deterministic explanation."""

    memory: MemoryRecord
    score: RecallScoreBreakdown
    explanation: str

    @property
    def total(self) -> float:
        return self.score.total


def normalize_text(value: str) -> str:
    """Collapse whitespace and case-fold text for equality/evidence checks."""

    if not isinstance(value, str):
        raise TypeError("text must be a string")
    return " ".join(value.split()).casefold()


def require_utc(value: datetime, *, field_name: str = "timestamp") -> datetime:
    """Return an aware UTC timestamp, rejecting naive datetimes consistently."""

    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def evidence_is_supported(source_text: str, evidence_excerpt: str) -> bool:
    """Check that normalized evidence is an actual source substring."""

    try:
        source = normalize_text(source_text)
        evidence = normalize_text(evidence_excerpt)
    except (TypeError, ValueError):
        return False
    return bool(evidence) and evidence in source


def _unit_interval(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError(f"{field_name} must be in [0, 1]")
    return result


def _candidate_key(value: CandidateLike) -> tuple[str, str, str, str, str]:
    return (
        normalize_text(value.content),
        str(value.memory_type),
        normalize_text(value.subject or ""),
        normalize_text(value.context_key or ""),
        normalize_text(value.attribute_key or ""),
    )


def proposition_key(value: CandidateLike) -> tuple[str, str, str, str, str]:
    """Return the normalized exact proposition key used for safe deduplication."""

    return _candidate_key(value)


def same_proposition(left: CandidateLike, right: CandidateLike) -> bool:
    """Return true only for the same typed proposition in the same context."""

    if not (_is_candidate_memory(left) or _is_memory_record(left)):
        return False
    if not (_is_candidate_memory(right) or _is_memory_record(right)):
        return False
    return proposition_key(left) == proposition_key(right)


def _action(
    decision_type: IngestDecisionType,
    reason_code: str,
    reason_summary: str,
    *,
    candidate_id: str | None = None,
    memory_id: UUID | None = None,
    related_memory_id: UUID | None = None,
    confidence: float | None = None,
) -> PolicyAction:
    return PolicyAction(
        decision_type=decision_type,
        reason_code=reason_code,
        reason_summary=reason_summary,
        candidate_id=candidate_id,
        memory_id=memory_id,
        related_memory_id=related_memory_id,
        confidence=confidence,
    )


def _reject(
    reason_code: str,
    reason_summary: str,
    *,
    candidate_id: str | None = None,
    related_memory_id: UUID | None = None,
    confidence: float | None = None,
) -> PolicyAction:
    return _action(
        IngestDecisionType.REJECTED,
        reason_code,
        reason_summary,
        candidate_id=candidate_id,
        related_memory_id=related_memory_id,
        confidence=confidence,
    )


def _skip(
    reason_code: str,
    reason_summary: str,
    *,
    candidate_id: str | None = None,
    confidence: float | None = None,
) -> PolicyAction:
    return _action(
        IngestDecisionType.SKIPPED,
        reason_code,
        reason_summary,
        candidate_id=candidate_id,
        confidence=confidence,
    )


def _validate_candidate_shape(candidate: CandidateMemory) -> str | None:
    from memoryos.contracts.ingestion import AdmissionSignals

    if not isinstance(candidate.candidate_id, str) or not candidate.candidate_id.strip():
        return "candidate_id must contain text"
    if not isinstance(candidate.content, str) or not normalize_text(candidate.content):
        return "candidate content must contain text"
    if not isinstance(candidate.memory_type, MemoryType):
        return "memory_type is not one of the supported memory types"
    try:
        _unit_interval(candidate.importance, field_name="importance")
        _unit_interval(candidate.confidence, field_name="confidence")
    except ValueError as exc:
        return str(exc)
    if candidate.admission is not None:
        if not isinstance(candidate.admission, AdmissionSignals):
            return "admission signals are not a supported structured value"
        try:
            AdmissionSignals.model_validate(candidate.admission.model_dump())
        except ValueError:
            return "admission signals contain unsupported values"
    for name in ("effective_at", "expires_at"):
        value = getattr(candidate, name)
        if value is not None:
            try:
                require_utc(value, field_name=name)
            except (TypeError, ValueError) as exc:
                return str(exc)
    if candidate.effective_at is not None and candidate.expires_at is not None:
        effective_at = require_utc(candidate.effective_at, field_name="effective_at")
        expires_at = require_utc(candidate.expires_at, field_name="expires_at")
        if expires_at <= effective_at:
            return "expires_at must be after effective_at"
    return None


def _is_filler(value: str) -> bool:
    return bool(_FILLER_RE.fullmatch(normalize_text(value)))


def _is_secret(value: str) -> bool:
    normalized = normalize_text(value)
    return bool(_SECRET_TERM_RE.search(normalized) or _SECRET_ASSIGNMENT_RE.search(normalized))


def validate_candidate(
    candidate: object,
    source_text: str,
    *,
    seen_candidate_ids: Collection[str] = (),
) -> CandidateValidation:
    """Validate one structured extraction before it can create a memory.

    Invalid model output is returned as a ``rejected`` action rather than
    raising or being coerced into an arbitrary write. Filler, secrets, and an
    explicit ``worth_remembering=False`` are represented as ``skipped``.
    """

    candidate_id = getattr(candidate, "candidate_id", None)
    if not _is_candidate_memory(candidate):
        return CandidateValidation(
            _reject(
                "unsupported_candidate",
                "Candidate proposal is not a supported CandidateMemory value.",
                candidate_id=candidate_id if isinstance(candidate_id, str) else None,
            )
        )

    candidate_id = candidate.candidate_id
    if candidate_id in seen_candidate_ids:
        return CandidateValidation(
            _reject(
                "duplicate_candidate_id",
                "Candidate ID was repeated within this interaction.",
                candidate_id=candidate_id,
            ),
            candidate,
        )

    shape_error = _validate_candidate_shape(candidate)
    if shape_error is not None:
        return CandidateValidation(
            _reject("invalid_candidate", shape_error, candidate_id=candidate_id), candidate
        )

    if not evidence_is_supported(source_text, candidate.evidence_excerpt):
        return CandidateValidation(
            _reject(
                "unsupported_evidence",
                "Candidate evidence is not a normalized substring of the source interaction.",
                candidate_id=candidate_id,
            ),
            candidate,
        )

    # The evidence guard is deliberately checked before these filters. A
    # model cannot cause a source-free filler/secret skip using invented text.
    if _is_filler(candidate.content) or _is_filler(candidate.evidence_excerpt):
        return CandidateValidation(
            _skip(
                "filler_content",
                "Conversational greeting or acknowledgement with no durable information.",
                candidate_id=candidate_id,
                confidence=float(candidate.confidence),
            ),
            candidate,
        )
    if _is_secret(candidate.content) and _is_secret(candidate.evidence_excerpt):
        return CandidateValidation(
            _skip(
                "sensitive_secret",
                "Credentials and secret material are never stored as memories.",
                candidate_id=candidate_id,
                confidence=float(candidate.confidence),
            ),
            candidate,
        )

    signals = candidate.admission
    if signals is None:
        return CandidateValidation(
            _skip(
                "admission_signals_missing",
                "Insufficient evidence of durable, useful information.",
                candidate_id=candidate_id,
                confidence=candidate.confidence,
            ),
            candidate,
        )

    non_memory_reasons = {
        "greeting": (
            "conversational_greeting",
            "Conversational greeting with no durable information.",
        ),
        "acknowledgement": (
            "conversational_acknowledgement",
            "Conversational acknowledgement with no durable information.",
        ),
        "chitchat": ("conversational_filler", "Conversational filler with no durable information."),
        "question": ("question_without_fact", "A question without a supported durable fact."),
        "one_off_request": (
            "temporary_request",
            "Temporary request unlikely to matter outside this interaction.",
        ),
    }
    rejection: tuple[str, str] | None = non_memory_reasons.get(signals.content_kind)
    if rejection is None and signals.evidence_source != "user":
        rejection = (
            ("assistant_generated", "Assistant-generated information lacks user evidence.")
            if signals.evidence_source == "assistant"
            else ("unsupported_inference", "Insufficient user evidence for a durable fact.")
        )
    if rejection is None and signals.durability != "lasting":
        rejection = (
            ("transient_information", "Temporary conversational state has no long-term value.")
            if signals.durability == "transient"
            else (
                "uncertain_durability",
                "Durability is uncertain; not suitable for long-term memory.",
            )
        )
    if rejection is None and signals.specificity != "specific":
        rejection = ("vague_information", "Too vague to support useful future recall.")
    expected_value = {
        MemoryType.PREFERENCE: "personalization",
        MemoryType.SEMANTIC: "reference",
        MemoryType.PROCEDURAL: "procedure",
        MemoryType.EPISODIC: "significant_event",
    }[candidate.memory_type]
    if rejection is None and signals.future_value != expected_value:
        rejection = ("no_future_value", "No clear future use for this memory type.")
    if rejection is None and not candidate.worth_remembering:
        rejection = ("candidate_declined", "No useful long-term information was identified.")
    if rejection is None and candidate.confidence < MIN_CONFIDENCE:
        rejection = ("low_confidence", "Insufficient confidence in the source-supported claim.")
    importance_floor = 0.55 if candidate.memory_type is MemoryType.EPISODIC else MIN_IMPORTANCE
    if rejection is None and candidate.importance < importance_floor:
        rejection = (
            "low_importance",
            "Limited future usefulness does not justify long-term storage.",
        )
    if rejection is not None:
        return CandidateValidation(
            _skip(
                *rejection,
                candidate_id=candidate_id,
                confidence=candidate.confidence,
            ),
            candidate,
        )
    return _accepted_candidate_validation(candidate)


def _accepted_candidate_validation(candidate: CandidateMemory) -> CandidateValidation:
    reasons = {
        MemoryType.PREFERENCE: "Stable preference with future personalization value.",
        MemoryType.SEMANTIC: "Specific, durable fact with future reference value.",
        MemoryType.PROCEDURAL: "Reusable instruction with future execution value.",
        MemoryType.EPISODIC: "Significant event with future historical value.",
    }
    return CandidateValidation(
        _action(
            IngestDecisionType.CREATED,
            f"admitted_{candidate.memory_type.value}",
            reasons[candidate.memory_type],
            candidate_id=candidate.candidate_id,
            confidence=candidate.confidence,
        ),
        candidate,
    )


def validate_candidates(candidates: Iterable[object], source_text: str) -> CandidateBatchValidation:
    """Validate and request-locally deduplicate a model extraction batch."""

    validations: list[CandidateValidation] = []
    seen_ids: set[str] = set()
    seen_keys: dict[tuple[str, str, str, str, str], CandidateMemory] = {}

    for candidate in candidates:
        result = validate_candidate(candidate, source_text, seen_candidate_ids=seen_ids)
        candidate_id = getattr(candidate, "candidate_id", None)
        if isinstance(candidate_id, str):
            seen_ids.add(candidate_id)

        if result.accepted and result.candidate is not None:
            key = proposition_key(result.candidate)
            first = seen_keys.get(key)
            if first is not None:
                validations.append(
                    CandidateValidation(
                        _reject(
                            "duplicate_candidate",
                            (
                                "The same proposition was proposed more than once in one "
                                "interaction; it cannot reinforce itself."
                            ),
                            candidate_id=result.candidate.candidate_id,
                        ),
                        result.candidate,
                    )
                )
                continue
            seen_keys[key] = result.candidate
        validations.append(result)

    return CandidateBatchValidation(tuple(validations))


def deduplicate_candidates(candidates: Iterable[CandidateMemory]) -> DeduplicationResult:
    """Keep the first exact proposition and report later request-local duplicates."""

    unique: list[CandidateMemory] = []
    duplicates: list[tuple[CandidateMemory, CandidateMemory]] = []
    seen: dict[tuple[str, str, str, str, str], CandidateMemory] = {}
    for candidate in candidates:
        key = proposition_key(candidate)
        original = seen.get(key)
        if original is None:
            seen[key] = candidate
            unique.append(candidate)
        else:
            duplicates.append((candidate, original))
    return DeduplicationResult(tuple(unique), tuple(duplicates))


def reinforced_confidence(existing_confidence: float, incoming_confidence: float) -> float:
    """Return bounded confidence after one distinct interaction confirms it."""

    old = _unit_interval(existing_confidence, field_name="existing_confidence")
    incoming = _unit_interval(incoming_confidence, field_name="incoming_confidence")
    proposed = min(MAX_REINFORCED_CONFIDENCE, old + 0.05 * incoming * (1.0 - old))
    # A historical value above the policy cap must never be reduced by a new
    # confirmation. The cap applies to increases, not retroactive repair.
    return max(old, proposed)


def validate_reinforcement(
    candidate: object,
    existing_memory: object,
    *,
    interaction_id: UUID | None,
    prior_interaction_ids: Collection[UUID] = (),
    trigger: str = "ingestion",
    used_candidate_ids: Collection[str] = (),
    relation_confidence: float | None = None,
    source_text: str | None = None,
) -> PolicyAction:
    """Permit reinforcement only for a source-supported same-context proposition.

    Exact normalized content is the fast path. A paraphrase additionally needs a
    high-confidence relationship assessment, compatible identity keys, enough
    deterministic proposition overlap, and no negation or replacement language.
    """

    candidate_id = getattr(candidate, "candidate_id", None)
    if not _is_candidate_memory(candidate) or not _is_memory_record(existing_memory):
        return _reject(
            "unsupported_reinforcement_input",
            "Reinforcement requires a supported candidate and memory record.",
            candidate_id=candidate_id if isinstance(candidate_id, str) else None,
        )
    if candidate.candidate_id in used_candidate_ids:
        return _reject(
            "duplicate_candidate",
            "A candidate cannot reinforce itself more than once in one interaction.",
            candidate_id=candidate.candidate_id,
            related_memory_id=existing_memory.id,
        )
    if not isinstance(trigger, str) or trigger.casefold() != "ingestion":
        return _reject(
            "retrieval_cannot_reinforce",
            "Recall and ranking reads never create reinforcement events.",
            candidate_id=candidate.candidate_id,
            related_memory_id=existing_memory.id,
        )
    if existing_memory.status is not MemoryStatus.ACTIVE:
        return _reject(
            "memory_not_active",
            "Only an active memory can be reinforced automatically.",
            candidate_id=candidate.candidate_id,
            related_memory_id=existing_memory.id,
        )
    if interaction_id is None or not isinstance(interaction_id, UUID):
        return _reject(
            "interaction_id_required",
            "Reinforcement requires the current interaction ID.",
            candidate_id=candidate.candidate_id,
            related_memory_id=existing_memory.id,
        )
    if interaction_id in prior_interaction_ids:
        return _reject(
            "duplicate_interaction",
            "The interaction already confirmed this memory and cannot reinforce it again.",
            candidate_id=candidate.candidate_id,
            related_memory_id=existing_memory.id,
        )
    if source_text is not None and _has_reinforcement_change_language(
        source_text, candidate.evidence_excerpt
    ):
        return _reject(
            "reinforcement_change_language",
            "Negation or temporal replacement language cannot reinforce a memory.",
            candidate_id=candidate.candidate_id,
            related_memory_id=existing_memory.id,
        )
    exact_match = same_proposition(candidate, existing_memory)
    if not exact_match:
        if source_text is None:
            return _reject(
                "reinforcement_source_required",
                "A paraphrase cannot be reinforced without source-backed interaction evidence.",
                candidate_id=candidate.candidate_id,
                related_memory_id=existing_memory.id,
            )
        if not evidence_is_supported(source_text, candidate.evidence_excerpt):
            return _reject(
                "unsupported_evidence",
                "Candidate evidence is not a normalized substring of the source interaction.",
                candidate_id=candidate.candidate_id,
                related_memory_id=existing_memory.id,
            )
        if relation_confidence is None or relation_confidence < REINFORCE_RELATION_CONFIDENCE:
            return _reject(
                "low_relation_confidence",
                (
                    "A paraphrase needs relationship confidence of at least "
                    f"{REINFORCE_RELATION_CONFIDENCE:.2f}."
                ),
                candidate_id=candidate.candidate_id,
                related_memory_id=existing_memory.id,
            )
        if not _same_reinforcement_identity(candidate, existing_memory):
            return _reject(
                "reinforcement_identity_mismatch",
                (
                    "Reinforcement requires the same subject and memory type, plus "
                    "compatible context and attribute keys."
                ),
                candidate_id=candidate.candidate_id,
                related_memory_id=existing_memory.id,
            )
        if not _same_semantic_proposition(candidate, existing_memory):
            return _reject(
                "semantic_proposition_mismatch",
                "The source does not support the same durable proposition as the related memory.",
                candidate_id=candidate.candidate_id,
                related_memory_id=existing_memory.id,
            )

    updated_confidence = reinforced_confidence(existing_memory.confidence, candidate.confidence)
    reason_code = (
        "same_proposition_new_interaction"
        if exact_match
        else "same_context_paraphrase_new_interaction"
    )
    reason_summary = (
        "Already represented by an existing memory; confirmed by this interaction."
        if exact_match
        else "A source-supported paraphrase confirms an existing memory in the same context."
    )
    return _action(
        IngestDecisionType.REINFORCED,
        reason_code,
        reason_summary,
        candidate_id=candidate.candidate_id,
        memory_id=existing_memory.id,
        related_memory_id=existing_memory.id,
        confidence=updated_confidence,
    )


def _as_candidate_map(
    candidates: Mapping[str, CandidateMemory] | Iterable[CandidateMemory],
) -> dict[str, CandidateMemory]:
    if isinstance(candidates, Mapping):
        return {key: value for key, value in candidates.items() if _is_candidate_memory(value)}
    return {
        candidate.candidate_id: candidate
        for candidate in candidates
        if _is_candidate_memory(candidate)
    }


def _as_memory_map(
    memories: Mapping[UUID, MemoryRecord] | Iterable[MemoryRecord],
) -> dict[UUID, MemoryRecord]:
    if isinstance(memories, Mapping):
        return {key: value for key, value in memories.items() if _is_memory_record(value)}
    return {memory.id: memory for memory in memories if _is_memory_record(memory)}


def _canonical_token(token: str) -> str:
    token = _TOKEN_ALIASES.get(token, token)
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def _key_tokens(value: str) -> set[str]:
    normalized = normalize_text(value).replace("_", " ").replace("-", " ")
    return {
        _canonical_token(token)
        for token in _WORD_RE.findall(normalized)
        if token not in _PROPOSITION_STOPWORDS
    }


def _compatible_context_key(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    left_tokens = _key_tokens(left)
    right_tokens = _key_tokens(right)
    return bool(left_tokens) and left_tokens == right_tokens


def _compatible_attribute_key(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    left_normalized = normalize_text(left)
    right_normalized = normalize_text(right)
    if left_normalized == right_normalized:
        return True
    shared = _key_tokens(left) & _key_tokens(right)
    return bool(shared - _GENERIC_KEY_TOKENS)


def _same_reinforcement_identity(left: CandidateMemory, right: MemoryRecord) -> bool:
    if left.memory_type is not right.memory_type:
        return False
    if not normalize_text(left.subject or "") or not normalize_text(right.subject or ""):
        return False
    if normalize_text(left.subject or "") != normalize_text(right.subject or ""):
        return False
    return _compatible_context_key(
        left.context_key, right.context_key
    ) and _compatible_attribute_key(left.attribute_key, right.attribute_key)


def _semantic_proposition_tokens(value: str, *, subject: str | None) -> set[str]:
    subject_tokens = _key_tokens(subject) if subject else set()
    text = re.sub(r"(?<=\w)['’]s\b", "", normalize_text(value))
    tokens = {
        _canonical_token(token)
        for token in _WORD_RE.findall(text)
        if token not in _PROPOSITION_STOPWORDS
    }
    return tokens - subject_tokens - _PROPOSITION_PREDICATES


def _same_semantic_proposition(candidate: CandidateMemory, existing: MemoryRecord) -> bool:
    candidate_tokens = _semantic_proposition_tokens(candidate.content, subject=candidate.subject)
    existing_tokens = _semantic_proposition_tokens(existing.content, subject=existing.subject)
    if not candidate_tokens or not existing_tokens:
        return False
    shared = candidate_tokens & existing_tokens
    # A shared subject, attribute name, or context is not a shared value.
    # For example, "primary editor" cannot make VS Code and Cursor equivalent.
    identity_tokens = _key_tokens(
        " ".join(
            value or ""
            for item in (candidate, existing)
            for value in (item.context_key, item.attribute_key)
        )
    )
    if not shared - identity_tokens:
        return False
    coverage = len(shared) / min(len(candidate_tokens), len(existing_tokens))
    if len(shared) >= 2 and coverage >= 0.60:
        return True
    return len(shared) == 1 and len(candidate_tokens) == len(existing_tokens) == 1


def _has_reinforcement_change_language(source_text: str, evidence_excerpt: str) -> bool:
    text = " ".join((source_text, evidence_excerpt))
    return bool(
        _REINFORCEMENT_NEGATION_RE.search(text) or _REINFORCEMENT_REPLACEMENT_RE.search(text)
    )


def _explicit_change(
    source_text: str,
    replacement_evidence: str | None,
    candidate: CandidateMemory,
    existing: MemoryRecord,
) -> bool:
    """Require a source-backed replacement clause tied to this changed value."""

    if not replacement_evidence or not evidence_is_supported(source_text, replacement_evidence):
        return False
    incoming = _semantic_proposition_tokens(candidate.content, subject=candidate.subject)
    previous = _semantic_proposition_tokens(existing.content, subject=existing.subject)
    new_value = incoming - previous
    identity = _key_tokens(candidate.attribute_key or "") | (incoming & previous)
    identity -= _key_tokens(candidate.context_key or "")
    if not new_value:
        return False
    # An unrelated correction elsewhere in a multi-statement interaction must
    # not authorize this update. The model supplies the narrow quote; each
    # sentence must independently connect the replacement to the proposition.
    for clause in re.split(r"[.!?;\n]+", replacement_evidence):
        tokens = _key_tokens(clause)
        if (
            _EXPLICIT_CHANGE_RE.search(clause)
            and not _UNCERTAIN_CHANGE_RE.search(clause)
            and tokens & new_value
            and tokens & (identity | (previous - incoming))
        ):
            return True
    return False


def _different_context(candidate: CandidateMemory, existing: MemoryRecord) -> bool:
    separate_context = bool(
        candidate.context_key
        and existing.context_key
        and not _compatible_context_key(candidate.context_key, existing.context_key)
    )
    separate_time = (
        candidate.expires_at is not None and candidate.expires_at <= existing.effective_at
    ) or (
        existing.expires_at is not None
        and candidate.effective_at is not None
        and existing.expires_at <= candidate.effective_at
    )
    return separate_context or separate_time


def _new_relationship(
    candidate: CandidateMemory, existing: MemoryRecord | None = None, *, contextual: bool = False
) -> PolicyAction:
    return _action(
        IngestDecisionType.CREATED,
        "contextual_coexistence" if contextual else "new_memory",
        "Different context; both memories remain valid."
        if contextual
        else "No equivalent existing memory.",
        candidate_id=candidate.candidate_id,
        related_memory_id=existing.id if contextual and existing is not None else None,
        confidence=candidate.confidence,
    )


def _dispute(
    reason_code: str,
    reason_summary: str,
    *,
    candidate_id: str,
    memory_id: UUID,
    confidence: float,
) -> PolicyAction:
    return _action(
        IngestDecisionType.DISPUTED,
        reason_code,
        reason_summary,
        candidate_id=candidate_id,
        related_memory_id=memory_id,
        confidence=confidence,
    )


def validate_relation(
    assessment: object,
    candidates: Mapping[str, CandidateMemory] | Iterable[CandidateMemory],
    related_memories: Mapping[UUID, MemoryRecord] | Iterable[MemoryRecord],
    source_text: str,
    *,
    interaction_id: UUID | None = None,
    prior_interaction_ids: Collection[UUID] = (),
    used_candidate_ids: Collection[str] = (),
) -> PolicyAction:
    """Validate a model relation against allowlisted IDs and source evidence.

    Known context/identity differences create independent memories. Supersession
    requires compatible identity, incompatible values, confidence >= 0.90, a
    source-backed replacement clause tied to the changed value, an active target,
    and a newer effective time. Ambiguous conflicts preserve both for review.
    """

    if not _is_relation_assessment(assessment):
        return _reject(
            "unsupported_relation",
            "Relation proposal is not a supported RelationAssessment.",
        )

    candidate_map = _as_candidate_map(candidates)
    memory_map = _as_memory_map(related_memories)
    candidate = candidate_map.get(assessment.candidate_id)
    if candidate is None:
        return _reject(
            "unknown_candidate_id",
            "Relation candidate_id is not in the current extraction batch.",
            candidate_id=assessment.candidate_id,
        )

    try:
        relation_confidence = _unit_interval(
            assessment.confidence,
            field_name="relation confidence",
        )
    except ValueError as exc:
        return _reject(
            "invalid_relation_confidence",
            str(exc),
            candidate_id=assessment.candidate_id,
        )

    if not evidence_is_supported(source_text, assessment.evidence_excerpt):
        return _reject(
            "unsupported_evidence",
            "Relation evidence is not a normalized substring of the source interaction.",
            candidate_id=assessment.candidate_id,
            related_memory_id=assessment.related_memory_id,
            confidence=relation_confidence,
        )

    relation = assessment.relation
    related_id = assessment.related_memory_id
    if relation is MemoryRelation.SKIP or (relation is MemoryRelation.NEW and related_id is None):
        if relation is MemoryRelation.SKIP and related_id is not None:
            return _reject(
                "unexpected_related_memory_id",
                f"Relation {relation.value} cannot target an existing memory.",
                candidate_id=assessment.candidate_id,
                related_memory_id=related_id,
                confidence=relation_confidence,
            )
        candidate_validation = validate_candidate(candidate, source_text)
        if relation is MemoryRelation.SKIP:
            return _skip(
                "model_skipped_candidate",
                assessment.reason_summary,
                candidate_id=candidate.candidate_id,
                confidence=relation_confidence,
            )
        if not candidate_validation.accepted:
            return candidate_validation.action
        existing_match = next(
            (
                memory
                for memory in sorted(memory_map.values(), key=lambda item: str(item.id))
                if memory.status in {MemoryStatus.ACTIVE, MemoryStatus.DISPUTED}
                and (
                    same_proposition(candidate, memory)
                    or (
                        assessment.value_comparison == "equivalent"
                        and _same_reinforcement_identity(candidate, memory)
                        and _same_semantic_proposition(candidate, memory)
                    )
                )
            ),
            None,
        )
        if existing_match is not None:
            if existing_match.status is MemoryStatus.DISPUTED:
                return _skip(
                    "pending_conflict_already_represented",
                    "Already represented in a pending conflict; resolve it in Memory Review.",
                    candidate_id=candidate.candidate_id,
                )
            return validate_reinforcement(
                candidate,
                existing_match,
                interaction_id=interaction_id,
                prior_interaction_ids=prior_interaction_ids,
                used_candidate_ids=used_candidate_ids,
                relation_confidence=relation_confidence,
                source_text=source_text,
            )
        contextual_match = next(
            (
                memory
                for memory in sorted(memory_map.values(), key=lambda item: str(item.id))
                if memory.memory_type is candidate.memory_type
                and normalize_text(memory.subject or "") == normalize_text(candidate.subject or "")
                and _compatible_attribute_key(candidate.attribute_key, memory.attribute_key)
                and _different_context(candidate, memory)
            ),
            None,
        )
        return _new_relationship(
            candidate, contextual_match, contextual=contextual_match is not None
        )

    if not isinstance(related_id, UUID):
        return _reject(
            "related_memory_id_required",
            f"Relation {relation.value} requires an allowlisted related memory ID.",
            candidate_id=candidate.candidate_id,
            confidence=relation_confidence,
        )
    existing = memory_map.get(related_id)
    if existing is None or existing.id != related_id:
        return _reject(
            "unknown_related_memory_id",
            "Relation related_memory_id is not in the allowlisted memory snapshot.",
            candidate_id=candidate.candidate_id,
            related_memory_id=related_id,
            confidence=relation_confidence,
        )

    candidate_validation = validate_candidate(candidate, source_text)
    if not candidate_validation.accepted:
        return candidate_validation.action
    if existing.status not in {MemoryStatus.ACTIVE, MemoryStatus.DISPUTED}:
        return _reject(
            "memory_not_current",
            "Historical or forgotten memories cannot be changed by ingestion.",
            candidate_id=candidate.candidate_id,
            related_memory_id=existing.id,
        )
    # Similarity retrieves candidates; it does not bind independent subjects,
    # attributes, or contexts into one lineage, even if the model proposes it.
    if (
        candidate.memory_type is not existing.memory_type
        or (
            candidate.subject
            and existing.subject
            and normalize_text(candidate.subject) != normalize_text(existing.subject)
        )
        or (
            candidate.attribute_key
            and existing.attribute_key
            and not _compatible_attribute_key(candidate.attribute_key, existing.attribute_key)
        )
    ):
        return _new_relationship(candidate)
    if _different_context(candidate, existing):
        return _new_relationship(candidate, existing, contextual=True)
    if any(
        memory.status is MemoryStatus.DISPUTED and same_proposition(candidate, memory)
        for memory in memory_map.values()
    ):
        return _skip(
            "pending_conflict_already_represented",
            "Already represented in a pending conflict; resolve it in Memory Review.",
            candidate_id=candidate.candidate_id,
        )
    if same_proposition(candidate, existing):
        return validate_reinforcement(
            candidate,
            existing,
            interaction_id=interaction_id,
            prior_interaction_ids=prior_interaction_ids,
            used_candidate_ids=used_candidate_ids,
            relation_confidence=relation_confidence,
            source_text=source_text,
        )
    if assessment.value_comparison == "distinct":
        return _new_relationship(candidate)
    if relation is MemoryRelation.REINFORCE:
        if assessment.value_comparison == "incompatible":
            return _dispute(
                "conflicting_values_need_review",
                "Incompatible claims without enough evidence to choose the current one.",
                candidate_id=candidate.candidate_id,
                memory_id=existing.id,
                confidence=relation_confidence,
            )
        return validate_reinforcement(
            candidate,
            existing,
            interaction_id=interaction_id,
            prior_interaction_ids=prior_interaction_ids,
            used_candidate_ids=used_candidate_ids,
            relation_confidence=relation_confidence,
            source_text=source_text,
        )

    if (
        assessment.value_comparison == "equivalent"
        and _same_reinforcement_identity(candidate, existing)
        and _same_semantic_proposition(candidate, existing)
    ):
        return validate_reinforcement(
            candidate,
            existing,
            interaction_id=interaction_id,
            prior_interaction_ids=prior_interaction_ids,
            used_candidate_ids=used_candidate_ids,
            relation_confidence=relation_confidence,
            source_text=source_text,
        )
    if relation is MemoryRelation.NEW and assessment.value_comparison != "incompatible":
        return _new_relationship(candidate)
    if relation in {MemoryRelation.DISPUTE, MemoryRelation.NEW}:
        return _dispute(
            "conflicting_values_need_review",
            "Incompatible claims without enough evidence to choose the current one.",
            candidate_id=candidate.candidate_id,
            memory_id=existing.id,
            confidence=relation_confidence,
        )

    if relation is not MemoryRelation.SUPERSEDE:
        return _reject(
            "unsupported_relation_type",
            "Relation type cannot produce a persistence action.",
            candidate_id=candidate.candidate_id,
            related_memory_id=existing.id,
            confidence=relation_confidence,
        )

    if not _same_reinforcement_identity(candidate, existing):
        return _dispute(
            "ambiguous_supersede_identity",
            "The proposition identity is uncertain; both claims are preserved for review.",
            candidate_id=candidate.candidate_id,
            memory_id=existing.id,
            confidence=relation_confidence,
        )
    if existing.status is MemoryStatus.DISPUTED:
        return _dispute(
            "pending_conflict_requires_review",
            "An unresolved conflict needs an owner decision before this value can change.",
            candidate_id=candidate.candidate_id,
            memory_id=existing.id,
            confidence=relation_confidence,
        )
    if relation_confidence < SUPERSEDE_RELATION_CONFIDENCE:
        return _dispute(
            "ambiguous_supersede_confidence",
            (
                "Supersession confidence is below the explicit correction threshold; "
                "both versions are preserved."
            ),
            candidate_id=candidate.candidate_id,
            memory_id=existing.id,
            confidence=relation_confidence,
        )
    if assessment.value_comparison != "incompatible":
        return _dispute(
            "unproven_value_change",
            "A different incompatible value was not established; both claims need review.",
            candidate_id=candidate.candidate_id,
            memory_id=existing.id,
            confidence=relation_confidence,
        )
    if not _explicit_change(source_text, assessment.replacement_evidence, candidate, existing):
        return _dispute(
            "ambiguous_supersede_change",
            (
                "A similarity or differing sentence alone does not prove a correction; "
                "both versions are preserved."
            ),
            candidate_id=candidate.candidate_id,
            memory_id=existing.id,
            confidence=relation_confidence,
        )

    if candidate.effective_at is None:
        return _dispute(
            "missing_effective_time",
            "Supersession requires an explicit effective time newer than the existing memory.",
            candidate_id=candidate.candidate_id,
            memory_id=existing.id,
            confidence=relation_confidence,
        )
    try:
        candidate_effective_at = require_utc(candidate.effective_at, field_name="effective_at")
        existing_effective_at = require_utc(existing.effective_at, field_name="effective_at")
    except (TypeError, ValueError) as exc:
        return _reject(
            "invalid_effective_time",
            str(exc),
            candidate_id=candidate.candidate_id,
            related_memory_id=existing.id,
            confidence=relation_confidence,
        )
    if candidate_effective_at <= existing_effective_at:
        return _reject(
            "stale_effective_time",
            "Older imported evidence cannot supersede a newer active memory.",
            candidate_id=candidate.candidate_id,
            related_memory_id=existing.id,
            confidence=relation_confidence,
        )

    return _action(
        IngestDecisionType.SUPERSEDED,
        "explicit_newer_correction",
        "Explicitly replaces the previous value; the old version remains in history.",
        candidate_id=candidate.candidate_id,
        related_memory_id=existing.id,
        confidence=relation_confidence,
    )


@dataclass(frozen=True, slots=True)
class ConsolidationPlan:
    sources: tuple[MemoryRecord, ...]
    canonical: MemoryRecord


@dataclass(frozen=True, slots=True)
class ConsolidationValidation:
    plan: ConsolidationPlan | None
    reason: str


def _candidate_from_record(memory: MemoryRecord) -> CandidateMemory:
    from memoryos.contracts.ingestion import CandidateMemory

    return CandidateMemory(
        candidate_id=str(memory.id),
        content=memory.content,
        memory_type=memory.memory_type,
        subject=memory.subject,
        context_key=memory.context_key,
        attribute_key=memory.attribute_key,
        importance=memory.importance,
        confidence=memory.confidence,
        evidence_excerpt=memory.content[:1000],
    )


def _consolidation_tokens(memory: CandidateMemory | MemoryRecord) -> set[str]:
    return _semantic_proposition_tokens(memory.content, subject=memory.subject) - _key_tokens(
        memory.context_key or ""
    )


def validate_consolidation(
    sources: Collection[MemoryRecord],
    *,
    as_of: datetime,
    candidate: CandidateMemory | None = None,
    relation_confidence: float = 1.0,
    automatic: bool = True,
) -> ConsolidationValidation:
    """Choose a verbatim source that covers equivalent, nested propositions.

    Retrieval/model equivalence only proposes the group. No generated summary
    or centroid can drop details: a preserved source must cover every source's
    substantive tokens. Incomparable values, negation, numbers, contexts, and
    timeframes fail closed. This intentionally misses less obvious paraphrases.
    """
    ordered = tuple(sorted(sources, key=lambda item: str(item.id)))

    def refuse(reason: str) -> ConsolidationValidation:
        return ConsolidationValidation(None, f"Kept separate — {reason}.")

    if len(ordered) < 2 or len(ordered) > 8 or len({m.id for m in ordered}) != len(ordered):
        return refuse("a consolidation requires 2–8 distinct sources")
    first = ordered[0]
    if any(len(m.content) > 2000 for m in ordered):
        return refuse("a source exceeds the canonical memory size limit")
    snapshot = require_utc(as_of, field_name="as_of")
    if any(m.status is not MemoryStatus.ACTIVE for m in ordered):
        return refuse("only active memories can be consolidated")
    if any(
        m.scope_id != first.scope_id
        or m.embedding_model != first.embedding_model
        or m.embedding_dimensions != first.embedding_dimensions
        for m in ordered
    ):
        return refuse("sources must share one scope and embedding space")
    reference = _candidate_from_record(first)
    if any(not _same_reinforcement_identity(reference, m) for m in ordered):
        return refuse("subjects, attributes, or contexts differ")
    if any(
        m.effective_at > snapshot or (m.expires_at and m.expires_at <= snapshot) for m in ordered
    ):
        return refuse("future or expired information cannot become current")
    if len({m.expires_at for m in ordered}) != 1:
        return refuse("the validity windows differ")
    if first.memory_type is MemoryType.EPISODIC and len({m.effective_at for m in ordered}) != 1:
        return refuse("distinct events must retain their own timeframes")
    if automatic and (
        relation_confidence < 0.95
        or min(m.confidence for m in ordered) < 0.90
        or candidate is None
        or candidate.confidence < 0.90
    ):
        return refuse("equivalence evidence is not strong enough for an automatic change")
    if len({normalize_text(m.content) for m in ordered}) > 1 and any(
        _has_reinforcement_change_language(m.content, m.content) for m in ordered
    ):
        return refuse("negation or change language needs human judgment")
    numeric_values = {tuple(re.findall(r"\b\d+(?:\.\d+)?\b", m.content)) for m in ordered}
    if len(numeric_values) != 1:
        return refuse("numeric values differ")
    values = {m.id: _consolidation_tokens(m) for m in ordered}
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            a, b = values[left.id], values[right.id]
            if (
                not a
                or not b
                or not (a <= b or b <= a)
                or not _same_semantic_proposition(_candidate_from_record(left), right)
            ):
                return refuse("the memories contain distinct or uncertain knowledge")
    canonical = max(ordered, key=lambda m: (len(values[m.id]), len(m.content), str(m.id)))
    if any(not value <= values[canonical.id] for value in values.values()):
        return refuse("no source preserves the full shared information")
    if candidate is not None and (
        not _same_reinforcement_identity(candidate, canonical)
        or not _same_semantic_proposition(candidate, canonical)
        or not _consolidation_tokens(candidate) <= values[canonical.id]
    ):
        return refuse("the incoming claim adds information or changes its context")
    return ConsolidationValidation(
        ConsolidationPlan(ordered, canonical),
        f"Overlaps with {len(ordered)} existing memories expressing the same durable proposition.",
    )


def _clamp_cosine(raw_similarity: float) -> float:
    if isinstance(raw_similarity, bool) or not isinstance(raw_similarity, (int, float)):
        raise ValueError("raw_similarity must be a finite number")
    if not math.isfinite(float(raw_similarity)):
        raise ValueError("raw_similarity must be a finite number")
    return max(-1.0, min(1.0, float(raw_similarity)))


def normalized_similarity(raw_similarity: float) -> float:
    """Clamp cosine to [-1, 1], then apply the contract's [0, 1] relevance floor."""

    return max(0.0, _clamp_cosine(raw_similarity))


def _validate_min_similarity(min_similarity: float) -> float:
    return _unit_interval(min_similarity, field_name="min_similarity")


def meets_relevance_floor(
    raw_similarity: float,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> bool:
    """Apply the similarity floor before importance can affect ranking."""

    return normalized_similarity(raw_similarity) >= _validate_min_similarity(min_similarity)


def is_eligible_for_recall(
    memory: MemoryRecord,
    as_of: datetime,
    *,
    include_disputed: bool = False,
    raw_similarity: float | None = None,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    embedding_model: str | None = None,
    embedding_dimensions: int | None = None,
) -> bool:
    """Return whether a memory may enter the recall ranking snapshot."""

    if not _is_memory_record(memory):
        return False
    evaluated_at = require_utc(as_of, field_name="as_of")
    floor = _validate_min_similarity(min_similarity)
    if memory.status is not MemoryStatus.ACTIVE and not (
        include_disputed and memory.status is MemoryStatus.DISPUTED
    ):
        return False
    effective_at = require_utc(memory.effective_at, field_name="effective_at")
    if effective_at > evaluated_at:
        return False
    if memory.expires_at is not None and (
        require_utc(memory.expires_at, field_name="expires_at") <= evaluated_at
    ):
        return False
    if (embedding_model is None) != (embedding_dimensions is None):
        return False
    if embedding_model is not None and (
        memory.embedding_model != embedding_model
        or memory.embedding_dimensions != embedding_dimensions
    ):
        return False
    if raw_similarity is not None and normalized_similarity(raw_similarity) < floor:
        return False
    return True


def calculate_recall_score(
    memory: MemoryRecord,
    raw_similarity: float,
    as_of: datetime,
) -> RecallScoreBreakdown:
    """Calculate the explainable MemoryOS ranking score at ``as_of``."""

    if not _is_memory_record(memory):
        raise TypeError("memory must be a MemoryRecord")
    evaluated_at = require_utc(as_of, field_name="as_of")
    raw = _clamp_cosine(raw_similarity)
    similarity = max(0.0, raw)
    importance = _unit_interval(memory.importance, field_name="importance")
    confidence = _unit_interval(memory.confidence, field_name="confidence")
    if memory.reinforcement_count < 0:
        raise ValueError("reinforcement_count must be non-negative")
    half_life = TYPE_HALF_LIVES_DAYS.get(memory.memory_type)
    if half_life is None:
        raise ValueError("memory_type has no configured half-life")

    confirmed_at = require_utc(memory.last_confirmed_at, field_name="last_confirmed_at")
    days_since_confirmation = max(0.0, (evaluated_at - confirmed_at).total_seconds() / 86_400.0)
    recency = 2.0 ** (-days_since_confirmation / half_life)
    reinforcement = min(1.0, math.log1p(memory.reinforcement_count) / math.log(6.0))

    weighted_similarity = SCORE_WEIGHTS["similarity"] * similarity
    weighted_importance = SCORE_WEIGHTS["importance"] * importance
    weighted_recency = SCORE_WEIGHTS["recency"] * recency
    weighted_reinforcement = SCORE_WEIGHTS["reinforcement"] * reinforcement
    weighted_confidence = SCORE_WEIGHTS["confidence"] * confidence
    total = (
        weighted_similarity
        + weighted_importance
        + weighted_recency
        + weighted_reinforcement
        + weighted_confidence
    )
    from memoryos.contracts.recall import RecallScoreBreakdown

    return RecallScoreBreakdown(
        policy_version=MEMORYOS_POLICY_VERSION,
        raw_similarity=raw,
        similarity=similarity,
        importance=importance,
        recency=recency,
        reinforcement=reinforcement,
        confidence=confidence,
        weighted_similarity=weighted_similarity,
        weighted_importance=weighted_importance,
        weighted_recency=weighted_recency,
        weighted_reinforcement=weighted_reinforcement,
        weighted_confidence=weighted_confidence,
        total=total,
        days_since_confirmation=days_since_confirmation,
        half_life_days=half_life,
    )


def score_explanation(score: RecallScoreBreakdown) -> str:
    """Build a stable human-readable explanation from a score breakdown."""

    if score.similarity >= 0.75:
        match_strength = "Strong"
    elif score.similarity >= 0.50:
        match_strength = "Moderate"
    else:
        match_strength = "Weak"
    days = f"{score.days_since_confirmation:.1f}".rstrip("0").rstrip(".")
    evidence = (
        "repeated supporting evidence" if score.reinforcement > 0 else "initial supporting evidence"
    )
    return (
        f"{match_strength} semantic match; confirmed {days} days ago, with {evidence}. "
        f"Semantic relevance {score.similarity:.2f}; importance {score.importance:.2f}; "
        f"recency {score.recency:.2f}; reinforcement {score.reinforcement:.2f}; "
        f"confidence {score.confidence:.2f}; final score {score.total:.2f}. "
        f"Policy {score.policy_version}."
    )


def memory_why_for_creation(
    memory_type: MemoryType,
    *,
    importance: float,
    confidence: float,
    conflict_found: bool = False,
) -> list[str]:
    """Return deterministic, plain-language reasons for retaining a memory.

    These reasons are intentionally derived from validated fields.  They do
    not claim explicit wording or an absence of conflicts unless the caller
    supplies that evidence.
    """

    _unit_interval(importance, field_name="importance")
    _unit_interval(confidence, field_name="confidence")
    type_reason = {
        MemoryType.PREFERENCE: "user preference captured from the interaction",
        MemoryType.SEMANTIC: "durable fact captured from the interaction",
        MemoryType.EPISODIC: "concrete event captured from the interaction",
        MemoryType.PROCEDURAL: "repeatable procedure captured from the interaction",
    }[memory_type]
    usefulness = (
        "high expected future usefulness"
        if float(importance) >= 0.75
        else "expected future usefulness"
    )
    reasons = [
        type_reason,
        usefulness,
        f"confidence {float(confidence):.2f}",
    ]
    reasons.append(
        "an active conflict was preserved for review"
        if conflict_found
        else "no conflicting active memory was selected"
    )
    return reasons


def memory_why_for_reinforcement(reinforcement_count: int) -> list[str]:
    """Return the stable reason appended after a distinct confirmation."""

    if reinforcement_count < 1:
        raise ValueError("reinforcement_count must be positive")
    return [f"confirmed by {reinforcement_count} separate interaction(s)"]


def memory_why_for_supersession(
    *,
    relation_confidence: float,
    reason_summary: str,
    explicit_change: bool = True,
) -> list[str]:
    """Return deterministic reasons for a validated replacement version."""

    _unit_interval(relation_confidence, field_name="relation_confidence")
    reasons = [
        "newer evidence accepted for the same attribute",
        f"relationship confidence {float(relation_confidence):.2f}",
    ]
    if explicit_change:
        reasons.append("source interaction contained explicit change language")
    summary = " ".join(str(reason_summary).split())
    if summary:
        reasons.append(summary[:500])
    return reasons


def score_memory(memory: MemoryRecord, raw_similarity: float, as_of: datetime) -> ScoredMemory:
    """Return a score plus deterministic explanation for one memory."""

    score = calculate_recall_score(memory, raw_similarity, as_of)
    return ScoredMemory(memory=memory, score=score, explanation=score_explanation(score))


def rank_scored_memories(scored_memories: Iterable[ScoredMemory]) -> list[ScoredMemory]:
    """Sort by total, then normalized similarity, then UUID for stable ties."""

    return sorted(
        scored_memories,
        key=lambda item: (-item.score.total, -item.score.similarity, str(item.memory.id)),
    )


def rank_recall_candidates(
    memories: Iterable[MemoryRecord],
    similarities: Mapping[UUID, float],
    as_of: datetime,
    *,
    include_disputed: bool = False,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    embedding_model: str | None = None,
    embedding_dimensions: int | None = None,
    limit: int | None = None,
) -> list[ScoredMemory]:
    """Filter and rank a fixed memory snapshot with deterministic tie breaks."""

    scored: list[ScoredMemory] = []
    for memory in memories:
        raw_similarity = similarities.get(memory.id)
        if raw_similarity is None:
            continue
        if not is_eligible_for_recall(
            memory,
            as_of,
            include_disputed=include_disputed,
            raw_similarity=raw_similarity,
            min_similarity=min_similarity,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
        ):
            continue
        scored.append(score_memory(memory, raw_similarity, as_of))
    ranked = rank_scored_memories(scored)
    return ranked if limit is None else ranked[: max(0, limit)]


__all__ = [
    "CandidateBatchValidation",
    "CandidateValidation",
    "DEFAULT_MIN_SIMILARITY",
    "DeduplicationResult",
    "MAX_REINFORCED_CONFIDENCE",
    "MEMORYOS_POLICY_VERSION",
    "MIN_CONFIDENCE",
    "MIN_IMPORTANCE",
    "PolicyAction",
    "REINFORCE_RELATION_CONFIDENCE",
    "SCORE_WEIGHTS",
    "SUPERSEDE_RELATION_CONFIDENCE",
    "ScoredMemory",
    "TYPE_HALF_LIVES_DAYS",
    "calculate_recall_score",
    "deduplicate_candidates",
    "evidence_is_supported",
    "is_eligible_for_recall",
    "meets_relevance_floor",
    "memory_why_for_creation",
    "memory_why_for_reinforcement",
    "memory_why_for_supersession",
    "normalize_text",
    "normalized_similarity",
    "proposition_key",
    "rank_recall_candidates",
    "rank_scored_memories",
    "reinforced_confidence",
    "require_utc",
    "same_proposition",
    "score_explanation",
    "score_memory",
    "validate_candidate",
    "validate_candidates",
    "validate_relation",
    "validate_reinforcement",
]
