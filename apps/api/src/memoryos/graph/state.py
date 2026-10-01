"""Typed state shared by the bounded LangGraph ingestion pipeline."""

from datetime import datetime
from typing import TypedDict
from uuid import UUID

from memoryos.contracts.ingestion import (
    CandidateMemory,
    IngestDecision,
    IngestInteractionRequest,
    IngestInteractionResponse,
    RelationAssessment,
)
from memoryos.contracts.memory import MemoryRecord
from memoryos.domain.policies import ConsolidationPlan, PolicyAction


class GraphState(TypedDict, total=False):
    request: IngestInteractionRequest
    interaction_id: UUID
    received_at: datetime
    occurred_at: datetime
    expected_revision: int
    embedding_model: str
    embedding_dimensions: int
    candidates: list[CandidateMemory]
    admitted_candidates: list[CandidateMemory]
    candidate_embeddings: list[list[float]]
    related_memories: dict[str, list[MemoryRecord]]
    relation_assessments: list[RelationAssessment]
    policy_actions: list[PolicyAction]
    consolidation_plans: dict[str, ConsolidationPlan]
    consolidation_blocked_ids: list[UUID]
    decisions: list[IngestDecision]
    memory_ids: list[UUID]
    warnings: list[str]
    stage_timings: dict[str, float]
    provider_mode: str
    response: IngestInteractionResponse
    error: str
