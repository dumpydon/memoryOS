"""Read, ranking, and lifecycle services shared by REST and MCP.

This module owns the service-level policy around persistence.  Transport adapters
only authenticate, validate request shapes, and call these methods; they never
reimplement recall ranking or lifecycle mutations.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from memoryos.config import Settings, get_settings
from memoryos.contracts.memory import (
    ForgetMemoryRequest,
    ForgetMemoryResponse,
    MemoryEvent,
    MemoryHistoryResponse,
    MemoryListResponse,
    MemoryRecord,
    ResolveMemoryRequest,
    ResolveMemoryResponse,
)
from memoryos.contracts.overview import MemoryTypeCount, OverviewResponse
from memoryos.contracts.recall import (
    RecallComparisonItem,
    RecallComparisonResponse,
    RecallItem,
    RecallRequest,
    RecallResponse,
)
from memoryos.db.errors import (
    IdempotencyConflict,
    InvalidEmbedding,
    ScopeNotFoundError,
    ScopeRevisionConflict,
)
from memoryos.db.models import Interaction, Memory, MemoryReview
from memoryos.db.models import MemoryEvent as MemoryEventRow
from memoryos.db.repositories import MemoryRepository, RecallCandidate
from memoryos.domain.enums import (
    ExecutionMode,
    MemoryEventType,
    MemoryStatus,
    MemoryType,
)
from memoryos.domain.policies import MEMORYOS_POLICY_VERSION, rank_recall_candidates, require_utc
from memoryos.providers.errors import (
    ProviderOutputInvalid,
    ProviderTimeout,
    ProviderUnavailable,
    UnsupportedDemoInput,
)
from memoryos.services.errors import ServiceError

DEMO_SCOPE_ID = UUID("00000000-0000-0000-0000-000000000001")
LIVE_SCOPE_ID = UUID("00000000-0000-0000-0000-000000000002")
DEMO_MODEL = "demo-fixture-v1"


def utc_now() -> datetime:
    return datetime.now(UTC)


def _event_contract(row: MemoryEventRow, *, memory_content: str | None = None) -> MemoryEvent:
    return MemoryEvent(
        id=row.id,
        scope_id=row.scope_id,
        memory_id=row.memory_id,
        interaction_id=row.interaction_id,
        event_type=row.event_type,
        related_memory_id=row.related_memory_id,
        evidence_excerpt=row.evidence_excerpt,
        reason_code=row.reason_code,
        reason_summary=row.reason_summary,
        before=row.before,
        after=row.after,
        memory_content=memory_content,
        created_at=row.created_at,
    )


def _error_from_db(exc: Exception) -> ServiceError:
    if isinstance(exc, ServiceError):
        return exc
    if isinstance(exc, ScopeNotFoundError):
        return ServiceError("not_found", str(exc))
    if isinstance(exc, ScopeRevisionConflict):
        return ServiceError("revision_conflict", str(exc), retryable=True)
    if isinstance(exc, IdempotencyConflict):
        return ServiceError("idempotency_conflict", str(exc))
    if isinstance(exc, InvalidEmbedding):
        return ServiceError("invalid_request", str(exc))
    if isinstance(exc, ValueError):
        return ServiceError("invalid_request", str(exc))
    # SQLAlchemy exceptions can contain connection strings, SQL text, or bound
    # parameters. Keep those details in the server traceback, never in a response.
    if exc.__class__.__module__.startswith("sqlalchemy"):
        return ServiceError(
            "database_unavailable",
            "The memory database is temporarily unavailable.",
            retryable=True,
        )
    return ServiceError("internal_error", "The memory operation could not be completed.")


class MemoryQueryService:
    """Synchronous service implementation used by both public transports."""

    def __init__(
        self,
        settings: Settings | None = None,
        session_factory: sessionmaker[Session] | None = None,
        *,
        embedding_factory: Callable[[ExecutionMode, Settings], Any] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if session_factory is None:
            from memoryos.db.session import create_session_factory

            session_factory = create_session_factory(self.settings)
            self._owns_session_factory = True
        else:
            self._owns_session_factory = False
        self.session_factory = session_factory
        self.embedding_factory = embedding_factory

    def close(self) -> None:
        """Dispose an internally-created factory; app-owned factories stay alive."""

        if self._owns_session_factory:
            bind = self.session_factory.kw.get("bind")
            dispose = getattr(bind, "dispose", None)
            if callable(dispose):
                dispose()

    def _session(self) -> AbstractContextManager[Session]:
        return self.session_factory()

    def _provider(
        self, mode: ExecutionMode
    ) -> tuple[str, int, Callable[[Sequence[str]], list[list[float]]]]:
        if mode is ExecutionMode.DEMO:
            from memoryos.seed.catalog import fixture_embeddings

            return DEMO_MODEL, self.settings.demo_embedding_dimensions, fixture_embeddings
        if self.embedding_factory is not None:
            provider = self.embedding_factory(mode, self.settings)
        else:
            try:
                from memoryos.providers.factory import make_embedding_provider
            except ImportError as exc:  # pragma: no cover - worker seam during staged rollout
                raise ServiceError(
                    "provider_unavailable",
                    "Live embedding provider is not configured.",
                    retryable=True,
                ) from exc
            provider = make_embedding_provider(mode, self.settings)
        model = getattr(provider, "model_name", self.settings.embedding_model)
        dimensions = int(getattr(provider, "dimensions", self.settings.embedding_dimensions))
        embed = getattr(provider, "embed", None)
        if not callable(embed):
            raise ServiceError(
                "provider_unavailable",
                "Embedding provider is unavailable.",
                retryable=True,
            )
        return model, dimensions, embed

    def _embed_query(self, *, query: str, mode: ExecutionMode) -> tuple[list[float], str, int]:
        try:
            model, dimensions, embed = self._provider(mode)
            vectors = embed([query])
        except UnsupportedDemoInput as exc:
            raise ServiceError(
                "unsupported_demo_input",
                "The demo query is not in the finite fixture catalog.",
            ) from exc
        except ProviderTimeout as exc:
            raise ServiceError("provider_timeout", str(exc), retryable=True) from exc
        except ProviderOutputInvalid as exc:
            raise ServiceError("provider_output_invalid", str(exc)) from exc
        except ProviderUnavailable as exc:
            raise ServiceError("provider_unavailable", str(exc), retryable=True) from exc
        except ValueError as exc:
            raise ServiceError(
                "provider_output_invalid",
                "Embedding provider returned an invalid query input.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:  # provider details must not cross the API boundary
            raise ServiceError(
                "provider_unavailable",
                "Embedding provider failed while evaluating the query.",
                retryable=True,
            ) from exc
        if not vectors or len(vectors) != 1:
            raise ServiceError(
                "provider_output_invalid",
                "Embedding provider returned no query vector.",
            )
        try:
            vector = [float(value) for value in vectors[0]]
        except (TypeError, ValueError) as exc:
            raise ServiceError(
                "provider_output_invalid",
                "Embedding provider returned a malformed query vector.",
            ) from exc
        if len(vector) != dimensions:
            raise ServiceError(
                "embedding_model_mismatch",
                f"Embedding provider returned {len(vector)} dimensions; expected {dimensions}.",
            )
        return vector, model, dimensions

    def _snapshot(self, request: RecallRequest) -> tuple[datetime, list[RecallCandidate], str, int]:
        try:
            evaluated_at = (
                require_utc(request.as_of, field_name="as_of") if request.as_of else utc_now()
            )
        except (TypeError, ValueError) as exc:
            raise ServiceError("invalid_request", str(exc)) from exc
        expected_model = (
            DEMO_MODEL if request.mode is ExecutionMode.DEMO else self.settings.embedding_model
        )
        # Check scope/model before invoking a provider. This keeps a request from
        # spending provider work for an unknown or incompatible namespace.
        try:
            with self.session_factory.begin() as session:
                scope = MemoryRepository(session, self.settings).require_scope(request.scope_id)
                if scope.embedding_model != expected_model:
                    raise ServiceError(
                        "embedding_model_mismatch",
                        "The scope embedding model does not match the requested mode.",
                    )
        except ServiceError:
            raise
        except Exception as exc:
            raise _error_from_db(exc) from exc
        vector, model, dimensions = self._embed_query(query=request.query, mode=request.mode)
        if model != expected_model:
            raise ServiceError(
                "embedding_model_mismatch",
                "The embedding provider model does not match the requested mode.",
            )
        try:
            with self._session() as session:
                repo = MemoryRepository(session, self.settings)
                candidates = list(
                    repo.list_active_for_recall(
                        request,
                        as_of=evaluated_at,
                        query_embedding=vector,
                        embedding_model=model,
                    )
                )
        except ServiceError:
            raise
        except Exception as exc:
            raise _error_from_db(exc) from exc
        return evaluated_at, candidates, model, dimensions

    def list_memories(
        self,
        *,
        scope_id: UUID,
        cursor: str | None = None,
        limit: int = 25,
        memory_types: list[MemoryType] | None = None,
        statuses: list[MemoryStatus] | None = None,
        search: str | None = None,
    ) -> MemoryListResponse:
        try:
            with self._session() as session:
                return MemoryRepository(session, self.settings).list_memories(
                    scope_id=scope_id,
                    cursor=cursor,
                    limit=limit,
                    memory_types=memory_types,
                    statuses=statuses,
                    search=search,
                )
        except Exception as exc:
            raise _error_from_db(exc) from exc

    def get_memory(self, *, scope_id: UUID, memory_id: UUID) -> MemoryRecord:
        try:
            with self._session() as session:
                record = MemoryRepository(session, self.settings).get_by_id(scope_id, memory_id)
        except Exception as exc:
            raise _error_from_db(exc) from exc
        if record is None:
            raise ServiceError("not_found", "Memory was not found in this scope.")
        return record

    def history(self, *, scope_id: UUID, memory_id: UUID) -> MemoryHistoryResponse:
        try:
            with self._session() as session:
                history = MemoryRepository(session, self.settings).get_history(
                    scope_id=scope_id, memory_id=memory_id
                )
        except Exception as exc:
            raise _error_from_db(exc) from exc
        if history is None:
            raise ServiceError("not_found", "Memory was not found in this scope.")
        return history

    def recall(self, request: RecallRequest) -> RecallResponse:
        evaluated_at, candidates, model, dimensions = self._snapshot(request)
        similarities = {
            candidate.record.id: candidate.raw_similarity
            for candidate in candidates
            if candidate.raw_similarity is not None
        }
        ranked = rank_recall_candidates(
            [candidate.record for candidate in candidates],
            similarities,
            evaluated_at,
            include_disputed=request.include_disputed,
            min_similarity=request.min_similarity,
            embedding_model=model,
            embedding_dimensions=dimensions,
            limit=request.limit,
        )
        return RecallResponse(
            scope_id=request.scope_id,
            query=request.query,
            evaluated_at=evaluated_at,
            policy_version=MEMORYOS_POLICY_VERSION,
            candidate_count=len(candidates),
            items=[
                RecallItem(
                    rank=index,
                    memory=item.memory,
                    score=item.score,
                    explanation=item.explanation,
                )
                for index, item in enumerate(ranked, start=1)
            ],
        )

    def compare(self, request: RecallRequest) -> RecallComparisonResponse:
        evaluated_at, candidates, model, dimensions = self._snapshot(request)
        similarities = {
            candidate.record.id: candidate.raw_similarity
            for candidate in candidates
            if candidate.raw_similarity is not None
        }
        scored = rank_recall_candidates(
            [candidate.record for candidate in candidates],
            similarities,
            evaluated_at,
            include_disputed=request.include_disputed,
            min_similarity=request.min_similarity,
            embedding_model=model,
            embedding_dimensions=dimensions,
        )
        score_by_id = {item.memory.id: item for item in scored}
        naive = sorted(
            (candidate for candidate in candidates if candidate.raw_similarity is not None),
            key=lambda candidate: (
                -max(0.0, candidate.raw_similarity or 0.0),
                str(candidate.record.id),
            ),
        )
        naive_rank = {candidate.record.id: index for index, candidate in enumerate(naive, start=1)}
        memoryos_rank = {item.memory.id: index for index, item in enumerate(scored, start=1)}

        def item_for(memory_id: UUID) -> RecallComparisonItem:
            candidate = next(
                candidate for candidate in candidates if candidate.record.id == memory_id
            )
            scored_memory = score_by_id[memory_id]
            naive_position = naive_rank.get(memory_id)
            memoryos_position = memoryos_rank.get(memory_id)
            delta = (
                naive_position - memoryos_position
                if naive_position is not None and memoryos_position is not None
                else None
            )
            return RecallComparisonItem(
                memory=candidate.record,
                naive_rank=naive_position,
                memoryos_rank=memoryos_position,
                naive_similarity=max(0.0, candidate.raw_similarity or 0.0),
                memoryos_score=scored_memory.score,
                rank_delta=delta,
                explanation=scored_memory.explanation,
            )

        naive_ids = [candidate.record.id for candidate in naive[: request.limit]]
        memoryos_ids = [item.memory.id for item in scored[: request.limit]]
        return RecallComparisonResponse(
            scope_id=request.scope_id,
            query=request.query,
            evaluated_at=evaluated_at,
            policy_version=MEMORYOS_POLICY_VERSION,
            candidate_count=len(candidates),
            naive=[item_for(memory_id) for memory_id in naive_ids],
            memoryos=[item_for(memory_id) for memory_id in memoryos_ids],
        )

    def forget(
        self,
        *,
        scope_id: UUID,
        memory_id: UUID,
        request: ForgetMemoryRequest,
    ) -> ForgetMemoryResponse:
        try:
            with self.session_factory.begin() as session:
                repo = MemoryRepository(session, self.settings)
                target = repo.get_stored_by_id(scope_id, memory_id)
                if target is None:
                    raise ServiceError("not_found", "Memory was not found in this scope.")
                scope = repo.require_scope(scope_id)
                forgotten_ids: list[UUID] = []
                with repo.mutation(scope_id=scope_id, expected_revision=scope.revision):
                    rows = list(
                        session.scalars(
                            select(Memory)
                            .where(
                                Memory.scope_id == scope_id,
                                Memory.lineage_id == target.record.lineage_id,
                            )
                            .with_for_update()
                        )
                    )
                    for row in rows:
                        if row.status is MemoryStatus.FORGOTTEN:
                            row.superseded_by_id = None
                            continue
                        before = {
                            "status": row.status.value,
                            "superseded_by_id": (
                                str(row.superseded_by_id) if row.superseded_by_id else None
                            ),
                        }
                        row.status = MemoryStatus.FORGOTTEN
                        row.superseded_by_id = None
                        forgotten_ids.append(row.id)
                        repo.insert_event(
                            scope_id=scope_id,
                            memory_id=row.id,
                            event_type=MemoryEventType.FORGOTTEN,
                            reason_code="owner_forgotten",
                            reason_summary=request.reason,
                            before=before,
                            after={
                                "status": MemoryStatus.FORGOTTEN.value,
                                "superseded_by_id": None,
                            },
                        )
                    session.flush()
                return ForgetMemoryResponse(
                    lineage_id=target.record.lineage_id,
                    forgotten_memory_ids=forgotten_ids,
                    reason=request.reason,
                )
        except ServiceError:
            raise
        except Exception as exc:
            raise _error_from_db(exc) from exc

    def resolve(
        self,
        *,
        scope_id: UUID,
        memory_id: UUID,
        request: ResolveMemoryRequest,
    ) -> ResolveMemoryResponse:
        try:
            with self.session_factory.begin() as session:
                repo = MemoryRepository(session, self.settings)
                target = repo.get_stored_by_id(scope_id, memory_id)
                if target is None:
                    raise ServiceError("not_found", "Memory was not found in this scope.")
                scope = repo.require_scope(scope_id)
                with repo.mutation(scope_id=scope_id, expected_revision=scope.revision):
                    rows = list(
                        session.scalars(
                            select(Memory)
                            .where(
                                Memory.scope_id == scope_id,
                                Memory.lineage_id == target.record.lineage_id,
                            )
                            .with_for_update()
                        )
                    )
                    selected = next(
                        (row for row in rows if row.id == request.selected_memory_id),
                        None,
                    )
                    if selected is None:
                        raise ServiceError(
                            "invalid_request",
                            "The selected memory is not in the target lineage.",
                        )
                    if selected.status is MemoryStatus.FORGOTTEN:
                        raise ServiceError(
                            "invalid_request",
                            "A forgotten memory cannot be reactivated by resolve.",
                        )
                    if not any(row.status is MemoryStatus.DISPUTED for row in rows):
                        raise ServiceError(
                            "invalid_request",
                            "The lineage has no disputed version to resolve.",
                        )

                    changed_ids: list[UUID] = []
                    # Make every non-forgotten sibling non-active first. This
                    # avoids a transient second active row before selecting the
                    # resolved version.
                    for row in rows:
                        if row.id == selected.id or row.status is MemoryStatus.FORGOTTEN:
                            continue
                        before = {
                            "status": row.status.value,
                            "superseded_by_id": (
                                str(row.superseded_by_id) if row.superseded_by_id else None
                            ),
                        }
                        if (
                            row.status is not MemoryStatus.SUPERSEDED
                            or row.superseded_by_id != selected.id
                        ):
                            row.status = MemoryStatus.SUPERSEDED
                            row.superseded_by_id = selected.id
                            changed_ids.append(row.id)
                            repo.insert_event(
                                scope_id=scope_id,
                                memory_id=row.id,
                                related_memory_id=selected.id,
                                event_type=MemoryEventType.SUPERSEDED,
                                reason_code="owner_resolved",
                                reason_summary=request.reason,
                                before=before,
                                after={
                                    "status": MemoryStatus.SUPERSEDED.value,
                                    "superseded_by_id": str(selected.id),
                                },
                            )
                    session.flush()
                    before_selected = {
                        "status": selected.status.value,
                        "superseded_by_id": (
                            str(selected.superseded_by_id) if selected.superseded_by_id else None
                        ),
                    }
                    if (
                        selected.status is not MemoryStatus.ACTIVE
                        or selected.superseded_by_id is not None
                    ):
                        selected.status = MemoryStatus.ACTIVE
                        selected.superseded_by_id = None
                        changed_ids.append(selected.id)
                    repo.insert_event(
                        scope_id=scope_id,
                        memory_id=selected.id,
                        event_type=MemoryEventType.RESOLVED,
                        reason_code="owner_resolved",
                        reason_summary=request.reason,
                        before=before_selected,
                        after={"status": MemoryStatus.ACTIVE.value, "superseded_by_id": None},
                    )
                    session.flush()
                return ResolveMemoryResponse(
                    lineage_id=target.record.lineage_id,
                    selected_memory_id=selected.id,
                    resolved_memory_ids=list(dict.fromkeys(changed_ids)),
                    reason=request.reason,
                )
        except ServiceError:
            raise
        except Exception as exc:
            raise _error_from_db(exc) from exc

    def get_overview(self, *, scope_id: UUID) -> OverviewResponse:
        now = utc_now()
        since = now - timedelta(days=30)
        try:
            with self.session_factory.begin() as session:
                repo = MemoryRepository(session, self.settings)
                repo.require_scope(scope_id)
                active_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(Memory)
                        .where(
                            Memory.scope_id == scope_id,
                            Memory.status == MemoryStatus.ACTIVE,
                        )
                    )
                    or 0
                )
                disputed_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(Memory)
                        .where(
                            Memory.scope_id == scope_id,
                            Memory.status == MemoryStatus.DISPUTED,
                        )
                    )
                    or 0
                )
                reinforced_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(MemoryEventRow)
                        .where(
                            MemoryEventRow.scope_id == scope_id,
                            MemoryEventRow.event_type == MemoryEventType.REINFORCED,
                            MemoryEventRow.created_at >= since,
                        )
                    )
                    or 0
                )
                interaction_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(Interaction)
                        .where(
                            Interaction.scope_id == scope_id,
                            Interaction.received_at >= since,
                        )
                    )
                    or 0
                )
                type_rows = session.execute(
                    select(Memory.memory_type, func.count())
                    .where(
                        Memory.scope_id == scope_id,
                        Memory.status == MemoryStatus.ACTIVE,
                    )
                    .group_by(Memory.memory_type)
                ).all()
                recent_rows = list(
                    session.execute(
                        select(MemoryEventRow, Memory.content)
                        .join(
                            Memory,
                            (Memory.scope_id == MemoryEventRow.scope_id)
                            & (Memory.id == MemoryEventRow.memory_id),
                        )
                        .where(MemoryEventRow.scope_id == scope_id)
                        .order_by(MemoryEventRow.created_at.desc(), MemoryEventRow.id.desc())
                        .limit(10)
                    )
                )
                recent_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(MemoryEventRow)
                        .where(
                            MemoryEventRow.scope_id == scope_id,
                            MemoryEventRow.created_at >= since,
                        )
                    )
                    or 0
                )
                unresolved_review_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(MemoryReview)
                        .where(
                            MemoryReview.scope_id == scope_id,
                            MemoryReview.status == "pending",
                        )
                    )
                    or 0
                )
                return OverviewResponse(
                    scope_id=scope_id,
                    active_memories=int(active_count),
                    disputed_memories=int(disputed_count),
                    reinforced_last_30_days=int(reinforced_count),
                    interactions_last_30_days=int(interaction_count),
                    type_counts=[
                        MemoryTypeCount(memory_type=memory_type, count=int(count))
                        for memory_type, count in type_rows
                    ],
                    recent_event_count=int(recent_count),
                    recent_events=[
                        _event_contract(row[0], memory_content=row[1]) for row in recent_rows
                    ],
                    generated_at=now,
                    unresolved_review_count=int(unresolved_review_count),
                )
        except Exception as exc:
            raise _error_from_db(exc) from exc


QueryService = MemoryQueryService


__all__ = [
    "DEMO_MODEL",
    "DEMO_SCOPE_ID",
    "LIVE_SCOPE_ID",
    "MemoryQueryService",
    "QueryService",
]
