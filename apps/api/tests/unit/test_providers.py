from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from memoryos.config import Settings
from memoryos.contracts.ingestion import CandidateMemory
from memoryos.contracts.memory import MemoryRecord
from memoryos.domain.enums import MemoryRelation, MemoryStatus, MemoryType
from memoryos.providers.demo import DemoEmbeddingProvider, DemoStructuredProvider
from memoryos.providers.errors import ProviderOutputInvalid, UnsupportedDemoInput
from memoryos.providers.factory import make_embedding_provider, make_structured_provider
from memoryos.providers.openai import CandidateBatch, OpenAIProvider, RelationBatch

SCOPE_ID = UUID("00000000-0000-0000-0000-000000000001")
MEMORY_ID = UUID("00000000-0000-0000-0000-000000000010")
NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _memory(*, status: MemoryStatus = MemoryStatus.ACTIVE) -> MemoryRecord:
    return MemoryRecord(
        id=MEMORY_ID,
        scope_id=SCOPE_ID,
        lineage_id=MEMORY_ID,
        version=1,
        content="Atlas prefers concise answers with Python examples.",
        memory_type=MemoryType.PREFERENCE,
        status=status,
        subject="Atlas",
        context_key="answer-style",
        attribute_key="response-format",
        importance=0.9,
        confidence=0.9,
        reinforcement_count=0,
        embedding_model="demo-fixture-v1",
        embedding_dimensions=1536,
        created_at=NOW,
        effective_at=NOW,
        last_confirmed_at=NOW,
    )


def test_demo_factory_and_fixture_embedding_are_bounded() -> None:
    settings = Settings()
    embedding = make_embedding_provider("demo", settings)
    structured = make_structured_provider("demo", settings)
    assert isinstance(embedding, DemoEmbeddingProvider)
    assert isinstance(structured, DemoStructuredProvider)
    vectors = embedding.embed(["Atlas prefers concise answers with Python examples."])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1536
    assert any(value != 0 for value in vectors[0])


def test_demo_providers_fail_closed_for_unknown_or_malformed_fixture_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    embedding = DemoEmbeddingProvider(settings)
    with pytest.raises(UnsupportedDemoInput):
        embedding.embed(["unallowlisted demo text"])

    import memoryos.seed.catalog as catalog

    monkeypatch.setattr(catalog, "fixture_embeddings", lambda texts: [[1.0]])
    with pytest.raises(ProviderOutputInvalid):
        embedding.embed(["Atlas prefers concise answers with Python examples."])


def test_demo_relations_match_active_target_and_new_has_no_target() -> None:
    provider = DemoStructuredProvider(Settings())
    candidate = CandidateMemory(
        candidate_id="demo:pref-python:reinforce",
        content="Atlas prefers concise answers with Python examples.",
        memory_type=MemoryType.PREFERENCE,
        subject="Atlas",
        context_key="answer-style",
        attribute_key="response-format",
        importance=0.9,
        confidence=0.95,
        evidence_excerpt="still prefers concise Python examples",
    )
    relation = provider.assess_relations(
        candidates=[candidate],
        related_memories=[_memory()],
    )[0]
    assert relation.relation is MemoryRelation.REINFORCE
    assert relation.related_memory_id == MEMORY_ID

    new_candidate = candidate.model_copy(
        update={
            "candidate_id": "demo:pref-python:new",
            "evidence_excerpt": "keep answers concise and use Python examples",
        }
    )
    new_relation = provider.assess_relations(
        candidates=[new_candidate],
        related_memories=[],
    )[0]
    assert new_relation.relation is MemoryRelation.NEW
    assert new_relation.related_memory_id is None


def test_live_relation_output_requires_every_candidate_once() -> None:
    provider = object.__new__(OpenAIProvider)
    provider.model_name = "gpt-test"
    provider._client = cast(
        Any,
        SimpleNamespace(
            responses=SimpleNamespace(
                parse=lambda **kwargs: SimpleNamespace(output_parsed=RelationBatch(relations=[]))
            )
        ),
    )
    candidate = CandidateMemory(
        candidate_id="c1",
        content="Atlas prefers concise answers.",
        memory_type=MemoryType.PREFERENCE,
        subject="Atlas",
        context_key="answer-style",
        attribute_key="response-format",
        importance=0.8,
        confidence=0.8,
        evidence_excerpt="prefers concise answers",
    )
    with pytest.raises(ProviderOutputInvalid, match="missing or duplicated"):
        provider.assess_relations(candidates=[candidate], related_memories=[])


def test_live_candidate_parsed_output_is_pydantic_validated() -> None:
    provider = object.__new__(OpenAIProvider)
    provider.model_name = "gpt-test"
    candidate = CandidateMemory(
        candidate_id="c1",
        content="Atlas prefers concise answers.",
        memory_type=MemoryType.PREFERENCE,
        subject="Atlas",
        context_key="answer-style",
        attribute_key="response-format",
        importance=0.8,
        confidence=0.8,
        evidence_excerpt="prefers concise answers",
    )
    provider._client = cast(
        Any,
        SimpleNamespace(
            responses=SimpleNamespace(
                parse=lambda **kwargs: SimpleNamespace(
                    output_parsed=CandidateBatch(candidates=[candidate])
                )
            )
        ),
    )
    provider.settings = Settings()
    assert provider.extract_candidates(text="Atlas prefers concise answers.") == [candidate]
