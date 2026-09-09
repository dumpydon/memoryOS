"""Deterministic demo providers backed by authored seed fixtures."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from memoryos.config import Settings
from memoryos.contracts.ingestion import CandidateMemory, RelationAssessment
from memoryos.contracts.memory import MemoryRecord
from memoryos.domain.enums import MemoryRelation, MemoryStatus
from memoryos.domain.policies import normalize_text
from memoryos.providers.errors import (
    ProviderError,
    ProviderOutputInvalid,
    ProviderUnavailable,
    UnsupportedDemoInput,
)

MAX_CANDIDATES = 5
MAX_RELATED_MEMORIES_PER_CANDIDATE = 5
MAX_RELATED_MEMORIES = MAX_CANDIDATES * MAX_RELATED_MEMORIES_PER_CANDIDATE


def _fixture_function(name: str) -> Any:
    try:
        catalog = import_module("memoryos.seed.catalog")
        function = getattr(catalog, name)
    except (ImportError, AttributeError) as exc:
        raise ProviderUnavailable("demo fixture catalog is unavailable") from exc
    if not callable(function):
        raise ProviderUnavailable("demo fixture catalog is unavailable")
    return function


def _raise_fixture_failure(exc: Exception, *, message: str) -> None:
    if getattr(exc, "code", None) == "unsupported_demo_input":
        raise exc
    if str(exc).casefold() == "unsupported demo input":
        raise UnsupportedDemoInput("unsupported demo input") from exc
    raise ProviderUnavailable(message) from exc


def _validate_vectors(
    vectors: object,
    *,
    expected_count: int,
    dimensions: int,
) -> list[list[float]]:
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        raise ProviderOutputInvalid("demo embedding output count is invalid")
    normalized: list[list[float]] = []
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != dimensions:
            raise ProviderOutputInvalid("demo embedding dimensions are invalid")
        values: list[float] = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ProviderOutputInvalid("demo embedding values are invalid")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ProviderOutputInvalid("demo embedding values are not finite")
            values.append(numeric)
        if not any(value != 0 for value in values):
            raise ProviderOutputInvalid("demo embedding has zero norm")
        normalized.append(values)
    return normalized


def _same_target(candidate: CandidateMemory, memory: MemoryRecord) -> bool:
    if candidate.memory_type is not memory.memory_type:
        return False
    for field in ("subject", "context_key", "attribute_key"):
        candidate_value = normalize_text(getattr(candidate, field) or "")
        memory_value = normalize_text(getattr(memory, field) or "")
        if not candidate_value or not memory_value or candidate_value != memory_value:
            return False
    return True


@dataclass(slots=True)
class DemoEmbeddingProvider:
    """Embedding adapter that delegates only to authored fixture vectors."""

    settings: Settings

    def __post_init__(self) -> None:
        self.model_name = self.settings.demo_embedding_model
        self.dimensions = self.settings.demo_embedding_dimensions

    model_name: str = ""
    dimensions: int = 1536

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if any(not isinstance(text, str) for text in texts):
            raise ProviderOutputInvalid("embedding input must be text")
        if not texts:
            return []
        try:
            raw = _fixture_function("fixture_embeddings")(list(texts))
        except ProviderError:
            raise
        except Exception as exc:
            _raise_fixture_failure(exc, message="demo embedding fixture failed")
        return _validate_vectors(raw, expected_count=len(texts), dimensions=self.dimensions)


@dataclass(slots=True)
class DemoStructuredProvider:
    """Structured adapter that delegates to finite fixture extraction/relations."""

    settings: Settings

    def __post_init__(self) -> None:
        self.model_name = "demo-fixtures"

    model_name: str = "demo-fixtures"

    def extract_candidates(self, *, text: str) -> list[CandidateMemory]:
        if not isinstance(text, str) or len(text) > self.settings.max_interaction_chars:
            raise ProviderOutputInvalid("interaction text exceeds the provider input bound")
        try:
            raw = _fixture_function("fixture_candidates")(text)
        except ProviderError:
            raise
        except Exception as exc:
            _raise_fixture_failure(exc, message="demo extraction fixture failed")
        if not isinstance(raw, list) or len(raw) > MAX_CANDIDATES:
            raise ProviderOutputInvalid("demo candidate output is invalid")
        candidates: list[CandidateMemory] = []
        ids: set[str] = set()
        for item in raw:
            if not isinstance(item, CandidateMemory) or item.candidate_id in ids:
                raise ProviderOutputInvalid(
                    "demo candidate output contains malformed or duplicate items"
                )
            ids.add(item.candidate_id)
            candidates.append(item)
        return candidates

    def assess_relations(
        self,
        *,
        candidates: Sequence[CandidateMemory],
        related_memories: Sequence[MemoryRecord],
    ) -> list[RelationAssessment]:
        if len(candidates) > MAX_CANDIDATES or len(related_memories) > MAX_RELATED_MEMORIES:
            raise ProviderOutputInvalid("demo relation input exceeds the provider bound")
        if any(not isinstance(item, CandidateMemory) for item in candidates):
            raise ProviderOutputInvalid("demo relation candidates are invalid")
        if any(not isinstance(item, MemoryRecord) for item in related_memories):
            raise ProviderOutputInvalid("demo related memories are invalid")
        if len({item.candidate_id for item in candidates}) != len(candidates):
            raise ProviderOutputInvalid("demo relation candidates contain duplicate IDs")

        try:
            fixture_relation = _fixture_function("fixture_relation")
            relations = [fixture_relation(item.candidate_id) for item in candidates]
        except ProviderError:
            raise
        except Exception as exc:
            _raise_fixture_failure(exc, message="demo relation fixture failed")

        results: list[RelationAssessment] = []
        for candidate, relation in zip(candidates, relations, strict=True):
            if not isinstance(relation, MemoryRelation):
                raise ProviderOutputInvalid("demo relation output is invalid")
            target = next(
                (
                    memory
                    for memory in sorted(
                        related_memories,
                        key=lambda item: (
                            0 if item.status is MemoryStatus.ACTIVE else 1,
                            str(item.id),
                        ),
                    )
                    if memory.status in {MemoryStatus.ACTIVE, MemoryStatus.DISPUTED}
                    and _same_target(candidate, memory)
                ),
                None,
            )
            if target is None and relation in {
                MemoryRelation.SUPERSEDE,
                MemoryRelation.DISPUTE,
            }:
                relation = MemoryRelation.NEW
            related_id = (
                target.id
                if target is not None
                and relation
                not in {
                    MemoryRelation.NEW,
                    MemoryRelation.SKIP,
                }
                else None
            )
            results.append(
                RelationAssessment(
                    candidate_id=candidate.candidate_id,
                    related_memory_id=related_id,
                    relation=relation,
                    confidence=1.0,
                    evidence_excerpt=candidate.evidence_excerpt,
                    reason_code=f"demo_{relation.value}",
                    reason_summary=(
                        "Authored demo new relation."
                        if relation is MemoryRelation.NEW
                        else (
                            "Authored demo skip relation."
                            if relation is MemoryRelation.SKIP
                            else (
                                "Authored demo relation with a matching scoped memory."
                                if target is not None
                                else "Authored demo relation has no matching scoped memory."
                            )
                        )
                    ),
                )
            )
        return results


__all__ = ["DemoEmbeddingProvider", "DemoStructuredProvider"]
