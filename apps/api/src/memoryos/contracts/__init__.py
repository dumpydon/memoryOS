"""Pydantic contracts used as the REST/OpenAPI source of truth."""

from memoryos.contracts.capabilities import CapabilitiesResponse
from memoryos.contracts.ingestion import (
    CandidateMemory,
    IngestDecision,
    IngestInteractionRequest,
    IngestInteractionResponse,
    InteractionTrace,
    RelationAssessment,
)
from memoryos.contracts.memory import (
    MemoryEvent,
    MemoryRecord,
    MemoryVersion,
)
from memoryos.contracts.recall import (
    RecallComparisonResponse,
    RecallItem,
    RecallRequest,
    RecallResponse,
    RecallScoreBreakdown,
)
from memoryos.contracts.review import (
    ConsolidationRequest,
    ResolveReviewRequest,
    ReviewItem,
    ReviewListResponse,
)

__all__ = [
    "CandidateMemory",
    "CapabilitiesResponse",
    "ConsolidationRequest",
    "IngestDecision",
    "IngestInteractionRequest",
    "IngestInteractionResponse",
    "InteractionTrace",
    "MemoryEvent",
    "MemoryRecord",
    "MemoryVersion",
    "RecallComparisonResponse",
    "RecallItem",
    "RecallRequest",
    "RecallResponse",
    "RecallScoreBreakdown",
    "RelationAssessment",
    "ResolveReviewRequest",
    "ReviewItem",
    "ReviewListResponse",
]
