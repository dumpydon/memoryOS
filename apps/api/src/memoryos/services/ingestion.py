"""Synchronous, bounded ingestion service.

Providers run before the mutation transaction. The graph produces a validated
plan from a scoped snapshot, then one repository mutation commits the
interaction, memory versions, events, and final decision payload atomically.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from memoryos.config import Settings
from memoryos.contracts.common import TraceStep
from memoryos.contracts.ingestion import (
    CandidateMemory,
    IngestDecision,
    IngestInteractionRequest,
    IngestInteractionResponse,
    InteractionTrace,
    RelationAssessment,
)
from memoryos.contracts.memory import MemoryRecord
from memoryos.db.errors import (
    DuplicateReinforcement,
    IdempotencyConflict,
    InvalidEmbedding,
    ScopeNotFoundError,
    ScopeRevisionConflict,
)
from memoryos.db.models import Memory
from memoryos.db.repositories import MemoryRepository
from memoryos.domain.enums import (
    ExecutionMode,
    IngestDecisionType,
    InteractionStatus,
    MemoryEventType,
    MemoryRelation,
    MemoryStatus,
)
from memoryos.domain.policies import (
    MEMORYOS_POLICY_VERSION,
    PolicyAction,
    require_utc,
    validate_candidates,
    validate_relation,
)
from memoryos.graph.factory import GraphNode, build_ingestion_graph
from memoryos.graph.state import GraphState
from memoryos.providers.errors import (
    ProviderError,
    ProviderOutputInvalid,
    ProviderTimeout,
    ProviderUnavailable,
    UnsupportedDemoInput,
)
from memoryos.providers.factory import make_embedding_provider, make_structured_provider
from memoryos.services.errors import ServiceError

MAX_CANDIDATES = 5
MAX_RELATED_MEMORIES_PER_CANDIDATE = 5
GRAPH_RECURSION_LIMIT = 12


def utc_now() -> datetime:
    return datetime.now(UTC)


def _hash_request(request: IngestInteractionRequest) -> str:
    """Hash user input without generated receive/occurred timestamps or the key."""

    payload = request.model_dump(mode="json", exclude={"idempotency_key", "occurred_at"})
    if request.occurred_at is not None:
        payload["occurred_at"] = require_utc(
            request.occurred_at, field_name="occurred_at"
        ).isoformat()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _expected_embedding_model(settings: Settings, mode: ExecutionMode) -> str:
    return settings.demo_embedding_model if mode is ExecutionMode.DEMO else settings.embedding_model


def _provider_error(exc: Exception) -> ServiceError:
    if isinstance(exc, ServiceError):
        return exc
    if isinstance(exc, ProviderTimeout):
        return ServiceError("provider_timeout", str(exc), retryable=True)
    if isinstance(exc, ProviderOutputInvalid):
        return ServiceError("provider_output_invalid", str(exc))
    if isinstance(exc, UnsupportedDemoInput):
        return ServiceError("unsupported_demo_input", "This demo input is not allowlisted.")
    if isinstance(exc, ProviderUnavailable):
        return ServiceError("provider_unavailable", str(exc), retryable=True)
    return ServiceError(
        "provider_unavailable", "A provider could not complete the request.", retryable=True
    )


def _db_error(exc: Exception) -> ServiceError:
    if isinstance(exc, ServiceError):
        return exc
    if isinstance(exc, ScopeNotFoundError):
        return ServiceError("not_found", "The requested scope was not found.")
    if isinstance(exc, IdempotencyConflict):
        return ServiceError(
            "idempotency_conflict", "The idempotency key belongs to another request."
        )
    if isinstance(exc, ScopeRevisionConflict):
        return ServiceError(
            "revision_conflict",
            "The scope changed while this interaction was processed.",
            retryable=True,
        )
    if isinstance(exc, DuplicateReinforcement):
        return ServiceError(
            "interaction_in_progress", "This interaction already reinforced the memory."
        )
    if isinstance(exc, InvalidEmbedding):
        return ServiceError(
            "embedding_model_mismatch", "The embedding does not match the configured model."
        )
    if isinstance(exc, (SQLAlchemyError, IntegrityError)):
        return ServiceError(
            "database_unavailable",
            "The memory database is temporarily unavailable.",
            retryable=True,
        )
    return ServiceError("internal_error", "The interaction could not be completed.")


def _as_decisions(actions: Iterable[PolicyAction]) -> list[IngestDecision]:
    return [action.to_decision() for action in actions]


def _trace_payload(
    *,
    mode: ExecutionMode,
    stage_timings: Mapping[str, float],
    candidates: Sequence[CandidateMemory],
    memory_ids: Sequence[UUID],
    action_by_candidate: Mapping[str, PolicyAction],
) -> dict[str, Any]:
    safe_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        action = action_by_candidate.get(candidate.candidate_id)
        item = candidate.model_dump(mode="json")
        if action is not None and action.reason_code == "sensitive_secret":
            item["content"] = "[redacted]"
            item["evidence_excerpt"] = "[redacted]"
        safe_candidates.append(item)
    steps = [
        {
            "node": node,
            "duration_ms": duration,
            "status": "completed",
        }
        for node, duration in stage_timings.items()
    ]
    return {
        "policy_version": MEMORYOS_POLICY_VERSION,
        "provider_mode": mode.value,
        "steps": steps,
        "candidates": safe_candidates,
        "memory_ids": [str(memory_id) for memory_id in memory_ids],
    }


def _response_from_interaction(
    interaction: Any,
    *,
    fallback_mode: ExecutionMode | None = None,
) -> IngestInteractionResponse:
    trace_payload = interaction.trace or {}
    mode_value = trace_payload.get("provider_mode", interaction.mode.value)
    try:
        mode = ExecutionMode(mode_value)
    except ValueError:
        mode = fallback_mode or interaction.mode
    candidates: list[CandidateMemory] = []
    for raw in trace_payload.get("candidates", []):
        try:
            candidates.append(CandidateMemory.model_validate(raw))
        except Exception:
            continue
    steps: list[TraceStep] = []
    for raw_step in trace_payload.get("steps", []):
        try:
            steps.append(TraceStep.model_validate(raw_step))
        except Exception:
            continue
    trace = InteractionTrace(
        steps=steps,
        policy_version=trace_payload.get("policy_version", MEMORYOS_POLICY_VERSION),
        provider_mode=mode,
    )
    decisions = []
    for raw_decision in interaction.decisions or []:
        try:
            decisions.append(IngestDecision.model_validate(raw_decision))
        except Exception:
            continue
    memory_ids: list[UUID] = []
    for raw_id in trace_payload.get("memory_ids", []):
        try:
            memory_ids.append(UUID(str(raw_id)))
        except (TypeError, ValueError):
            continue
    return IngestInteractionResponse(
        interaction_id=interaction.id,
        scope_id=interaction.scope_id,
        status=interaction.status,
        mode=interaction.mode,
        candidates=candidates,
        decisions=decisions,
        memory_ids=memory_ids,
        warnings=[],
        trace=trace,
    )


class MemoryIngestionService:
    """Bounded ingestion implementation shared by REST and MCP transports."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        *,
        embedding_factory: Callable[[ExecutionMode, Settings], Any] = make_embedding_provider,
        structured_factory: Callable[[ExecutionMode, Settings], Any] = make_structured_provider,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.embedding_factory = embedding_factory
        self.structured_factory = structured_factory

    def _session(self) -> AbstractContextManager[Session]:
        return self.session_factory()

    def _validate_request(self, request: IngestInteractionRequest) -> None:
        if len(request.text) > self.settings.max_interaction_chars:
            raise ServiceError("invalid_request", "Interaction text exceeds the configured limit.")
        if not request.preview and not request.idempotency_key:
            raise ServiceError(
                "invalid_request", "Committed interactions require an idempotency key."
            )
        if request.occurred_at is not None:
            try:
                require_utc(request.occurred_at, field_name="occurred_at")
            except (TypeError, ValueError) as exc:
                raise ServiceError("invalid_request", str(exc)) from exc

    def _scope_snapshot(
        self,
        request: IngestInteractionRequest,
    ) -> tuple[int, str]:
        expected_model = _expected_embedding_model(self.settings, request.mode)
        try:
            with self._session() as session:
                scope = MemoryRepository(session, self.settings).require_scope(request.scope_id)
        except Exception as exc:
            raise _db_error(exc) from exc
        if scope.embedding_model != expected_model:
            raise ServiceError(
                "embedding_model_mismatch",
                "The scope embedding model does not match the requested mode.",
            )
        return scope.revision, expected_model

    def _existing_request(
        self,
        request: IngestInteractionRequest,
        request_hash: str,
    ) -> IngestInteractionResponse | None:
        if not request.idempotency_key:
            return None
        try:
            with self._session() as session:
                repo = MemoryRepository(session, self.settings)
                repo.require_scope(request.scope_id)
                interaction = repo.get_interaction_by_idempotency(
                    scope_id=request.scope_id,
                    idempotency_key=request.idempotency_key,
                    request_hash=request_hash,
                )
        except Exception as exc:
            raise _db_error(exc) from exc
        if interaction is None:
            return None
        if interaction.status is InteractionStatus.PROCESSING:
            raise ServiceError(
                "interaction_in_progress",
                "An interaction with this idempotency key is still processing.",
                retryable=True,
            )
        return _response_from_interaction(interaction, fallback_mode=request.mode)

    def _providers(self, mode: ExecutionMode) -> tuple[Any, Any, str, int]:
        try:
            embedding = self.embedding_factory(mode, self.settings)
            structured = self.structured_factory(mode, self.settings)
        except Exception as exc:
            raise _provider_error(exc) from exc
        model = getattr(embedding, "model_name", None)
        dimensions = getattr(embedding, "dimensions", None)
        if (
            not isinstance(model, str)
            or not model
            or not isinstance(dimensions, int)
            or dimensions < 1
        ):
            raise ServiceError("provider_output_invalid", "Embedding provider metadata is invalid.")
        expected_model = _expected_embedding_model(self.settings, mode)
        if model != expected_model:
            raise ServiceError(
                "embedding_model_mismatch",
                "Embedding provider model does not match the requested mode.",
            )
        return embedding, structured, model, dimensions

    def _build_nodes(
        self,
        *,
        request: IngestInteractionRequest,
        interaction_id: UUID,
        received_at: datetime,
        occurred_at: datetime,
        expected_revision: int,
    ) -> dict[str, GraphNode]:
        embedding_provider, structured_provider, model, dimensions = self._providers(request.mode)

        def extract(state: GraphState) -> GraphState:
            try:
                raw_candidates = structured_provider.extract_candidates(text=request.text)
            except Exception as exc:
                raise _provider_error(exc) from exc
            if not isinstance(raw_candidates, list) or len(raw_candidates) > MAX_CANDIDATES:
                raise ProviderOutputInvalid("provider returned too many candidates")
            candidates: list[CandidateMemory] = []
            ids: set[str] = set()
            for candidate in raw_candidates:
                if not isinstance(candidate, CandidateMemory) or candidate.candidate_id in ids:
                    raise ProviderOutputInvalid(
                        "provider returned malformed or duplicate candidates"
                    )
                ids.add(candidate.candidate_id)
                if candidate.effective_at is None:
                    candidate = candidate.model_copy(update={"effective_at": occurred_at})
                candidates.append(candidate)
            return {"candidates": candidates}

        def embed(state: GraphState) -> GraphState:
            candidates = state.get("candidates", [])
            try:
                vectors = embedding_provider.embed([candidate.content for candidate in candidates])
            except Exception as exc:
                raise _provider_error(exc) from exc
            if not isinstance(vectors, list) or len(vectors) != len(candidates):
                raise ProviderOutputInvalid("provider returned an invalid embedding count")
            normalized: list[list[float]] = []
            for vector in vectors:
                if not isinstance(vector, list) or len(vector) != dimensions:
                    raise ProviderOutputInvalid("provider returned invalid embedding dimensions")
                if any(
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    for value in vector
                ):
                    raise ProviderOutputInvalid("provider returned invalid embedding values")
                values = [float(value) for value in vector]
                if not all(math.isfinite(value) for value in values) or not any(values):
                    raise ProviderOutputInvalid("provider returned an invalid embedding vector")
                normalized.append(values)
            return {"candidate_embeddings": normalized}

        def find_related(state: GraphState) -> GraphState:
            candidates = state.get("candidates", [])
            vectors = state.get("candidate_embeddings", [])
            related: dict[str, list[MemoryRecord]] = {}
            try:
                with self._session() as session:
                    repo = MemoryRepository(session, self.settings)
                    for index, candidate in enumerate(candidates):
                        rows = repo.related_candidates(
                            scope_id=request.scope_id,
                            attribute_key=candidate.attribute_key,
                            context_key=candidate.context_key,
                            query_embedding=vectors[index] if index < len(vectors) else None,
                            embedding_model=model,
                            memory_type=candidate.memory_type,
                            statuses=[MemoryStatus.ACTIVE],
                            include_disputed=False,
                            as_of=received_at,
                            limit=MAX_RELATED_MEMORIES_PER_CANDIDATE,
                        )
                        if not rows:
                            rows = repo.related_candidates(
                                scope_id=request.scope_id,
                                attribute_key=candidate.attribute_key,
                                context_key=candidate.context_key,
                                query_embedding=vectors[index] if index < len(vectors) else None,
                                embedding_model=model,
                                memory_type=candidate.memory_type,
                                statuses=[MemoryStatus.DISPUTED],
                                include_disputed=True,
                                as_of=received_at,
                                limit=MAX_RELATED_MEMORIES_PER_CANDIDATE,
                            )
                        related[candidate.candidate_id] = [row.record for row in rows]
            except Exception as exc:
                raise _db_error(exc) from exc
            return {"related_memories": related}

        def assess_relations(state: GraphState) -> GraphState:
            candidates = state.get("candidates", [])
            related_map = state.get("related_memories", {})
            unique: dict[UUID, MemoryRecord] = {}
            for candidate in candidates:
                for record in related_map.get(candidate.candidate_id, []):
                    unique[record.id] = record
            related_snapshot = list(unique.values())[
                : MAX_CANDIDATES * MAX_RELATED_MEMORIES_PER_CANDIDATE
            ]
            try:
                # ``source_text`` gives the live model the complete evidence
                # boundary needed to distinguish a correction from a paraphrase.
                # Keep compatibility with older injected providers that implement
                # the original two-keyword protocol.
                relation_method = structured_provider.assess_relations
                try:
                    parameters = inspect.signature(relation_method).parameters
                except (TypeError, ValueError):
                    accepts_source = False
                else:
                    accepts_source = "source_text" in parameters or any(
                        parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters.values()
                    )
                relation_kwargs: dict[str, Any] = {
                    "candidates": candidates,
                    "related_memories": related_snapshot,
                }
                if accepts_source:
                    relation_kwargs["source_text"] = request.text
                relations = relation_method(**relation_kwargs)
            except Exception as exc:
                raise _provider_error(exc) from exc
            if not isinstance(relations, list) or len(relations) != len(candidates):
                raise ProviderOutputInvalid("provider returned missing or extra relations")
            relation_ids = [
                item.candidate_id for item in relations if isinstance(item, RelationAssessment)
            ]
            if (
                len(relation_ids) != len(relations)
                or len(set(relation_ids)) != len(relation_ids)
                or set(relation_ids) != {item.candidate_id for item in candidates}
            ):
                raise ProviderOutputInvalid("provider returned malformed relation IDs")
            return {"relation_assessments": relations}

        def validate_plan(state: GraphState) -> GraphState:
            candidates = state.get("candidates", [])
            batch = validate_candidates(candidates, request.text)
            validation_by_id = {
                result.action.candidate_id: result
                for result in batch.validations
                if result.action.candidate_id is not None
            }
            relation_map = {
                item.candidate_id: item for item in state.get("relation_assessments", [])
            }
            all_related = {
                record.id: record
                for records in state.get("related_memories", {}).values()
                for record in records
            }
            actions: list[PolicyAction] = []
            used_targets: set[UUID] = set()
            used_candidate_ids: set[str] = set()
            has_relations = bool(state.get("relation_assessments"))
            for candidate in candidates:
                validation = validation_by_id.get(candidate.candidate_id)
                if validation is None:
                    actions.append(
                        PolicyAction(
                            decision_type=IngestDecisionType.REJECTED,
                            reason_code="candidate_validation_missing",
                            reason_summary="Candidate validation did not produce a result.",
                            candidate_id=candidate.candidate_id,
                        )
                    )
                    continue
                if not validation.accepted:
                    actions.append(validation.action)
                    continue
                if not has_relations:
                    action = PolicyAction(
                        decision_type=IngestDecisionType.CREATED,
                        reason_code="new_candidate",
                        reason_summary="Accepted candidate has no matching existing memory.",
                        candidate_id=candidate.candidate_id,
                        confidence=candidate.confidence,
                    )
                else:
                    assessment = relation_map.get(candidate.candidate_id)
                    if assessment is None:
                        raise ProviderOutputInvalid("provider omitted a candidate relation")
                    action = validate_relation(
                        assessment,
                        {candidate.candidate_id: candidate},
                        all_related,
                        request.text,
                        interaction_id=interaction_id,
                        used_candidate_ids=used_candidate_ids,
                    )
                if action.related_memory_id is not None and action.decision_type in {
                    IngestDecisionType.REINFORCED,
                    IngestDecisionType.SUPERSEDED,
                    IngestDecisionType.DISPUTED,
                }:
                    if action.related_memory_id in used_targets:
                        action = replace(
                            action,
                            decision_type=IngestDecisionType.REJECTED,
                            reason_code="duplicate_relation_target",
                            reason_summary=(
                                "Only one candidate may mutate a related memory per interaction."
                            ),
                        )
                    else:
                        target_id = action.related_memory_id
                        if target_id is not None:
                            used_targets.add(target_id)
                if action.decision_type is IngestDecisionType.REINFORCED:
                    used_candidate_ids.add(candidate.candidate_id)
                actions.append(action)
            return {"policy_actions": actions, "decisions": _as_decisions(actions)}

        def persist(state: GraphState) -> GraphState:
            persist_started = perf_counter()

            def timings_with_persist() -> dict[str, float]:
                timings = dict(state.get("stage_timings", {}))
                timings["persist"] = (perf_counter() - persist_started) * 1000
                return timings

            actions = state.get("policy_actions", [])
            candidates = state.get("candidates", [])
            by_id = {candidate.candidate_id: candidate for candidate in candidates}
            vectors = {
                candidate.candidate_id: vector
                for candidate, vector in zip(
                    candidates, state.get("candidate_embeddings", []), strict=False
                )
            }
            relation_by_id = {
                item.candidate_id: item for item in state.get("relation_assessments", [])
            }
            if request.preview:
                action_map = {
                    action.candidate_id: action for action in actions if action.candidate_id
                }
                response = IngestInteractionResponse(
                    interaction_id=interaction_id,
                    scope_id=request.scope_id,
                    status=InteractionStatus.PREVIEW,
                    mode=request.mode,
                    candidates=[
                        CandidateMemory.model_validate(item)
                        for item in _trace_payload(
                            mode=request.mode,
                            stage_timings=timings_with_persist(),
                            candidates=candidates,
                            memory_ids=[],
                            action_by_candidate=action_map,
                        )["candidates"]
                    ],
                    decisions=_as_decisions(actions),
                    memory_ids=[],
                    warnings=[],
                    trace=InteractionTrace(
                        steps=_steps(timings_with_persist()),
                        policy_version=MEMORYOS_POLICY_VERSION,
                        provider_mode=request.mode,
                    ),
                )
                return {"response": response, "memory_ids": []}

            memory_ids: list[UUID] = []
            action_map = {action.candidate_id: action for action in actions if action.candidate_id}
            trace = _trace_payload(
                mode=request.mode,
                stage_timings=timings_with_persist(),
                candidates=candidates,
                memory_ids=memory_ids,
                action_by_candidate=action_map,
            )
            try:
                with self.session_factory.begin() as session:
                    repo = MemoryRepository(session, self.settings)
                    scope = repo.require_scope(request.scope_id)
                    if scope.embedding_model != model:
                        raise ServiceError(
                            "embedding_model_mismatch",
                            "The scope embedding model changed during ingestion.",
                        )
                    with repo.mutation(
                        scope_id=request.scope_id,
                        expected_revision=expected_revision,
                    ):
                        interaction = repo.insert_interaction(
                            scope_id=request.scope_id,
                            text=request.text,
                            request_hash=_hash_request(request),
                            idempotency_key=request.idempotency_key,
                            provenance=request.source_ref,
                            source_ref=request.source_ref,
                            occurred_at=occurred_at,
                            received_at=received_at,
                            status=InteractionStatus.PROCESSING,
                            mode=request.mode,
                            metadata=request.metadata,
                            trace=trace,
                            interaction_id=interaction_id,
                        )
                        final_actions: list[PolicyAction] = []
                        for action in actions:
                            candidate = by_id.get(action.candidate_id or "")
                            relation = relation_by_id.get(action.candidate_id or "")
                            if candidate is None:
                                final_actions.append(action)
                                continue
                            evidence = (
                                relation.evidence_excerpt
                                if relation
                                else candidate.evidence_excerpt
                            )
                            if action.decision_type is IngestDecisionType.CREATED:
                                inserted = repo.insert_memory(
                                    scope_id=request.scope_id,
                                    content=candidate.content,
                                    memory_type=candidate.memory_type,
                                    importance=candidate.importance,
                                    confidence=candidate.confidence,
                                    embedding=vectors.get(candidate.candidate_id, []),
                                    embedding_model=model,
                                    status=MemoryStatus.ACTIVE,
                                    subject=candidate.subject,
                                    context_key=candidate.context_key,
                                    attribute_key=candidate.attribute_key,
                                    created_at=received_at,
                                    effective_at=candidate.effective_at or occurred_at,
                                    last_confirmed_at=occurred_at,
                                    expires_at=candidate.expires_at,
                                )
                                memory_ids.append(inserted.record.id)
                                repo.insert_event(
                                    scope_id=request.scope_id,
                                    memory_id=inserted.record.id,
                                    interaction_id=interaction.id,
                                    event_type=MemoryEventType.CREATED,
                                    related_memory_id=None,
                                    evidence_excerpt=evidence,
                                    relation=MemoryRelation.NEW,
                                    reason_code=action.reason_code,
                                    reason_summary=action.reason_summary,
                                    provenance=request.source_ref,
                                )
                                final_actions.append(replace(action, memory_id=inserted.record.id))
                            elif action.decision_type is IngestDecisionType.REINFORCED:
                                existing = repo.get_stored_by_id(
                                    request.scope_id, action.memory_id or UUID(int=0)
                                )
                                if existing is None:
                                    raise ServiceError(
                                        "not_found", "The related memory no longer exists."
                                    )
                                confirmed_at = max(
                                    existing.record.last_confirmed_at,
                                    occurred_at,
                                )
                                before = {
                                    "confidence": existing.record.confidence,
                                    "reinforcement_count": existing.record.reinforcement_count,
                                }
                                repo.reinforce_memory(
                                    scope_id=request.scope_id,
                                    memory_id=existing.record.id,
                                    interaction_id=interaction.id,
                                    evidence_excerpt=evidence,
                                    reason_code=action.reason_code,
                                    reason_summary=action.reason_summary,
                                    provenance=request.source_ref,
                                    before=before,
                                    after={
                                        "confidence": action.confidence,
                                        "reinforcement_count": existing.record.reinforcement_count
                                        + 1,
                                        "relation_confidence": (
                                            relation.confidence if relation is not None else None
                                        ),
                                    },
                                    confirmed_at=confirmed_at,
                                )
                                self._set_confidence(
                                    session,
                                    scope_id=request.scope_id,
                                    memory_id=existing.record.id,
                                    confidence=action.confidence,
                                )
                                memory_ids.append(existing.record.id)
                                final_actions.append(action)
                            elif action.decision_type in {
                                IngestDecisionType.SUPERSEDED,
                                IngestDecisionType.DISPUTED,
                            }:
                                existing = repo.get_stored_by_id(
                                    request.scope_id,
                                    action.related_memory_id or UUID(int=0),
                                )
                                if existing is None:
                                    raise ServiceError(
                                        "not_found", "The related memory no longer exists."
                                    )
                                new_id = uuid.uuid4()
                                versions = session.scalars(
                                    select(Memory.version).where(
                                        Memory.scope_id == request.scope_id,
                                        Memory.lineage_id == existing.record.lineage_id,
                                    )
                                ).all()
                                next_version = (
                                    max(versions) if versions else existing.record.version
                                ) + 1
                                # The composite superseded_by foreign key is
                                # immediate, while the active-version index
                                # permits only one active row. Stage a
                                # replacement as disputed, then point the old
                                # row at it and activate it in this transaction.
                                staged_status = MemoryStatus.DISPUTED
                                if action.decision_type is IngestDecisionType.DISPUTED:
                                    repo.set_memory_state(
                                        scope_id=request.scope_id,
                                        memory_id=existing.record.id,
                                        status=MemoryStatus.DISPUTED,
                                    )
                                inserted = repo.insert_memory(
                                    scope_id=request.scope_id,
                                    content=candidate.content,
                                    memory_type=candidate.memory_type,
                                    importance=candidate.importance,
                                    confidence=candidate.confidence,
                                    embedding=vectors.get(candidate.candidate_id, []),
                                    embedding_model=model,
                                    status=staged_status,
                                    subject=candidate.subject,
                                    context_key=candidate.context_key,
                                    attribute_key=candidate.attribute_key,
                                    lineage_id=existing.record.lineage_id,
                                    version=next_version,
                                    memory_id=new_id,
                                    created_at=received_at,
                                    effective_at=candidate.effective_at or occurred_at,
                                    last_confirmed_at=occurred_at,
                                    expires_at=candidate.expires_at,
                                )
                                if action.decision_type is IngestDecisionType.SUPERSEDED:
                                    repo.set_memory_state(
                                        scope_id=request.scope_id,
                                        memory_id=existing.record.id,
                                        status=MemoryStatus.SUPERSEDED,
                                        superseded_by_id=new_id,
                                    )
                                    repo.set_memory_state(
                                        scope_id=request.scope_id,
                                        memory_id=inserted.record.id,
                                        status=MemoryStatus.ACTIVE,
                                    )
                                memory_ids.extend([existing.record.id, inserted.record.id])
                                repo.insert_event(
                                    scope_id=request.scope_id,
                                    memory_id=inserted.record.id,
                                    interaction_id=interaction.id,
                                    event_type=(
                                        MemoryEventType.SUPERSEDED
                                        if action.decision_type is IngestDecisionType.SUPERSEDED
                                        else MemoryEventType.DISPUTED
                                    ),
                                    related_memory_id=existing.record.id,
                                    evidence_excerpt=evidence,
                                    relation=(
                                        MemoryRelation.SUPERSEDE
                                        if action.decision_type is IngestDecisionType.SUPERSEDED
                                        else MemoryRelation.DISPUTE
                                    ),
                                    reason_code=action.reason_code,
                                    reason_summary=action.reason_summary,
                                    provenance=request.source_ref,
                                )
                                final_actions.append(
                                    replace(
                                        action,
                                        memory_id=inserted.record.id,
                                        related_memory_id=existing.record.id,
                                    )
                                )
                            else:
                                final_actions.append(action)
                        memory_ids = list(dict.fromkeys(memory_ids))
                        final_decisions = _as_decisions(final_actions)
                        trace = _trace_payload(
                            mode=request.mode,
                            stage_timings=timings_with_persist(),
                            candidates=candidates,
                            memory_ids=memory_ids,
                            action_by_candidate={
                                decision.candidate_id: action
                                for decision, action in zip(
                                    final_decisions, final_actions, strict=True
                                )
                                if decision.candidate_id
                            },
                        )
                        repo.update_interaction(
                            scope_id=request.scope_id,
                            interaction_id=interaction.id,
                            status=InteractionStatus.COMPLETED,
                            decisions=final_decisions,
                            trace=trace,
                        )
                        response = IngestInteractionResponse(
                            interaction_id=interaction.id,
                            scope_id=request.scope_id,
                            status=InteractionStatus.COMPLETED,
                            mode=request.mode,
                            candidates=[
                                CandidateMemory.model_validate(item) for item in trace["candidates"]
                            ],
                            decisions=final_decisions,
                            memory_ids=memory_ids,
                            warnings=[],
                            trace=InteractionTrace(
                                steps=[TraceStep.model_validate(step) for step in trace["steps"]],
                                policy_version=MEMORYOS_POLICY_VERSION,
                                provider_mode=request.mode,
                            ),
                        )
                        return {"response": response, "memory_ids": memory_ids}
            except (ScopeRevisionConflict, IdempotencyConflict):
                raise
            except Exception as exc:
                raise _db_error(exc) from exc

        return {
            "extract": extract,
            "embed": embed,
            "find_related": find_related,
            "assess_relations": assess_relations,
            "validate_plan": validate_plan,
            "persist": persist,
        }

    @staticmethod
    def _set_confidence(
        session: Session,
        *,
        scope_id: UUID,
        memory_id: UUID,
        confidence: float | None,
    ) -> None:
        if confidence is None:
            return
        session.execute(
            update(Memory)
            .where(Memory.scope_id == scope_id, Memory.id == memory_id)
            .values(confidence=float(confidence))
        )
        session.flush()

    def ingest(self, request: IngestInteractionRequest) -> IngestInteractionResponse:
        self._validate_request(request)
        request_hash = _hash_request(request)
        replay = self._existing_request(request, request_hash)
        if replay is not None:
            return replay
        received_at = utc_now()
        occurred_at = (
            require_utc(request.occurred_at, field_name="occurred_at")
            if request.occurred_at is not None
            else received_at
        )
        for attempt in range(2):
            expected_revision, _ = self._scope_snapshot(request)
            interaction_id = uuid.uuid4()
            try:
                nodes = self._build_nodes(
                    request=request,
                    interaction_id=interaction_id,
                    received_at=received_at,
                    occurred_at=occurred_at,
                    expected_revision=expected_revision,
                )
                graph = build_ingestion_graph(nodes=nodes)
                state: GraphState = {
                    "request": request,
                    "interaction_id": interaction_id,
                    "received_at": received_at,
                    "occurred_at": occurred_at,
                    "expected_revision": expected_revision,
                    "embedding_model": _expected_embedding_model(self.settings, request.mode),
                    "embedding_dimensions": self.settings.demo_embedding_dimensions
                    if request.mode is ExecutionMode.DEMO
                    else self.settings.embedding_dimensions,
                    "stage_timings": {},
                    "provider_mode": request.mode.value,
                }
                result = graph.invoke(state, config={"recursion_limit": GRAPH_RECURSION_LIMIT})
                response = result.get("response")
                if not isinstance(response, IngestInteractionResponse):
                    raise ServiceError(
                        "internal_error", "The ingestion graph returned no response."
                    )
                return response
            except ScopeRevisionConflict as exc:
                if attempt == 0:
                    continue
                raise _db_error(exc) from exc
            except IdempotencyConflict:
                replay = self._existing_request(request, request_hash)
                if replay is not None:
                    return replay
                raise ServiceError(
                    "idempotency_conflict", "The idempotency key belongs to another request."
                ) from None
            except (
                ProviderError,
                ProviderTimeout,
                ProviderUnavailable,
                ProviderOutputInvalid,
            ) as exc:
                raise _provider_error(exc) from exc
            except ServiceError:
                raise
            except Exception as exc:
                mapped = _db_error(exc)
                if mapped.code == "internal_error":
                    raise _provider_error(exc) from exc
                raise mapped from exc
        raise ServiceError(
            "revision_conflict",
            "The scope changed while this interaction was processed.",
            retryable=True,
        )

    def get_interaction(
        self,
        *,
        scope_id: UUID,
        interaction_id: UUID,
    ) -> IngestInteractionResponse:
        try:
            with self._session() as session:
                repo = MemoryRepository(session, self.settings)
                repo.require_scope(scope_id)
                interaction = repo.get_interaction(scope_id=scope_id, interaction_id=interaction_id)
        except Exception as exc:
            raise _db_error(exc) from exc
        if interaction is None:
            raise ServiceError("not_found", "The interaction was not found in this scope.")
        return _response_from_interaction(interaction)


def _steps(stage_timings: Mapping[str, float]) -> list[TraceStep]:
    return [
        TraceStep(node=name, duration_ms=duration, status="completed")
        for name, duration in stage_timings.items()
    ]


__all__ = ["MemoryIngestionService"]
