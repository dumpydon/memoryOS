"""Provider seams. Live and fixture adapters must implement these methods."""

from collections.abc import Sequence
from typing import Protocol

from memoryos.contracts.ingestion import CandidateMemory, RelationAssessment
from memoryos.contracts.memory import MemoryRecord


class StructuredMemoryProvider(Protocol):
    model_name: str

    def extract_candidates(self, *, text: str) -> list[CandidateMemory]: ...

    def assess_relations(
        self,
        *,
        candidates: Sequence[CandidateMemory],
        related_memories: Sequence[MemoryRecord],
        source_text: str | None = None,
    ) -> list[RelationAssessment]: ...


class EmbeddingProvider(Protocol):
    model_name: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
