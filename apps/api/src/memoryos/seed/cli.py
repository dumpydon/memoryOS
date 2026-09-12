"""Idempotent PostgreSQL loader for the authored demo catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from memoryos.config import Settings, get_settings
from memoryos.db.models import Memory
from memoryos.db.models import MemoryEvent as MemoryEventRow
from memoryos.db.repositories import MemoryRepository
from memoryos.db.session import create_session_factory
from memoryos.domain.enums import (
    ExecutionMode,
    InteractionStatus,
    MemoryEventType,
    MemoryRelation,
    MemoryStatus,
)
from memoryos.seed.catalog import (
    DEMO_MODEL,
    DEMO_SCOPE_ID,
    LIVE_SCOPE_ID,
    SeedMemorySpec,
    fixture_embeddings,
    seed_specs,
)


@dataclass(frozen=True, slots=True)
class SeedSummary:
    demo_scope_id: str
    live_scope_id: str
    inserted_memories: int
    inserted_events: int
    already_seeded: bool


def _request_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _seed_interaction_key(spec: SeedMemorySpec, suffix: str = "created") -> str:
    return f"demo-seed:{spec.key}:{suffix}"


def _ensure_scopes(session: Session, settings: Settings) -> None:
    repo = MemoryRepository(session, settings)
    if repo.get_scope(DEMO_SCOPE_ID) is None:
        repo.create_scope(
            scope_id=DEMO_SCOPE_ID,
            name="Atlas public demo",
            embedding_model=DEMO_MODEL,
        )
    if repo.get_scope(LIVE_SCOPE_ID) is None:
        repo.create_scope(
            scope_id=LIVE_SCOPE_ID,
            name="Atlas private live",
            embedding_model=settings.embedding_model,
        )


def _write_spec(
    session: Session,
    repo: MemoryRepository,
    spec: SeedMemorySpec,
    known: dict[str, Memory],
) -> tuple[int, int]:
    vector = fixture_embeddings([spec.content])[0]
    stored = repo.insert_memory(
        scope_id=DEMO_SCOPE_ID,
        memory_id=spec.id,
        lineage_id=spec.lineage_id,
        version=spec.version,
        content=spec.content,
        memory_type=spec.memory_type,
        status=spec.status,
        subject=spec.subject,
        context_key=spec.context_key,
        attribute_key=spec.attribute_key,
        importance=spec.importance,
        confidence=spec.confidence,
        reinforcement_count=spec.reinforcement_count,
        embedding=vector,
        embedding_model=DEMO_MODEL,
        effective_at=spec.effective_at,
        last_confirmed_at=spec.last_confirmed_at,
        expires_at=spec.expires_at,
    )
    row = session.get(Memory, stored.record.id)
    if row is None:
        raise RuntimeError("seeded memory was not visible after insert")
    known[spec.key] = row
    event_count = 0

    interaction = repo.insert_interaction(
        scope_id=DEMO_SCOPE_ID,
        interaction_id=spec.id,
        text=spec.content,
        request_hash=_request_hash(spec.content),
        idempotency_key=_seed_interaction_key(spec),
        provenance=f"demo-fixture:{spec.key}",
        occurred_at=spec.effective_at,
        received_at=spec.effective_at,
        status=InteractionStatus.COMPLETED,
        mode=ExecutionMode.DEMO,
        metadata={"fixture": True, "seed_key": spec.key},
    )
    event_type = {
        MemoryStatus.ACTIVE: MemoryEventType.CREATED,
        MemoryStatus.DISPUTED: MemoryEventType.DISPUTED,
        MemoryStatus.SUPERSEDED: MemoryEventType.SUPERSEDED,
        MemoryStatus.FORGOTTEN: MemoryEventType.FORGOTTEN,
    }[spec.status]
    relation = {
        MemoryStatus.ACTIVE: MemoryRelation.NEW,
        MemoryStatus.DISPUTED: MemoryRelation.DISPUTE,
        MemoryStatus.SUPERSEDED: MemoryRelation.SUPERSEDE,
        MemoryStatus.FORGOTTEN: None,
    }[spec.status]
    repo.insert_event(
        scope_id=DEMO_SCOPE_ID,
        memory_id=spec.id,
        interaction_id=interaction.id,
        event_type=event_type,
        relation=relation,
        reason_code=(
            "demo_ambiguous_conflict"
            if spec.status is MemoryStatus.DISPUTED
            else "demo_seed"
        ),
        reason_summary=(
            "Two plausible values share the same subject, context, and attribute "
            "without clear correction evidence."
            if spec.status is MemoryStatus.DISPUTED
            else "Authored MemoryOS demo fixture."
        ),
        provenance="demo-fixture",
        after={"status": spec.status.value, "seed_key": spec.key},
    )
    event_count += 1
    for index in range(spec.reinforcement_count):
        reinforcement_text = f"{spec.content} Confirmation {index + 1}."
        reinforcement_interaction = repo.insert_interaction(
            scope_id=DEMO_SCOPE_ID,
            text=reinforcement_text,
            request_hash=_request_hash(reinforcement_text),
            idempotency_key=_seed_interaction_key(spec, f"reinforced-{index + 1}"),
            provenance=f"demo-fixture:{spec.key}:reinforcement-{index + 1}",
            occurred_at=spec.last_confirmed_at,
            received_at=spec.last_confirmed_at,
            status=InteractionStatus.COMPLETED,
            mode=ExecutionMode.DEMO,
            metadata={"fixture": True, "seed_key": spec.key, "reinforcement": index + 1},
        )
        repo.insert_event(
            scope_id=DEMO_SCOPE_ID,
            memory_id=spec.id,
            interaction_id=reinforcement_interaction.id,
            event_type=MemoryEventType.REINFORCED,
            relation=MemoryRelation.REINFORCE,
            reason_code="demo_seed_reinforcement",
            reason_summary="Authored fixture confirmation.",
            provenance="demo-fixture",
            after={"reinforcement_count": index + 1, "seed_key": spec.key},
        )
        event_count += 1
    return 1, event_count


def _ensure_demo_reviews(session: Session, repo: MemoryRepository) -> None:
    """Backfill review items for demos seeded before the Phase 2 migration."""

    disputed_events = list(
        session.scalars(
            select(MemoryEventRow)
            .where(
                MemoryEventRow.scope_id == DEMO_SCOPE_ID,
                MemoryEventRow.event_type == MemoryEventType.DISPUTED,
            )
            .order_by(MemoryEventRow.created_at, MemoryEventRow.id)
        )
    )
    for event in disputed_events:
        review = repo.ensure_conflict_review(event)
        if review is not None and review.reason_code == "demo_seed":
            review.reason_code = "demo_ambiguous_conflict"
            review.reason_summary = (
                "Two plausible values share the same subject, context, and attribute "
                "without clear correction evidence."
            )


def seed_demo(
    settings: Settings | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
) -> SeedSummary:
    """Create both fixed scopes and load missing demo rows without resetting data."""

    runtime = settings or get_settings()
    owns_factory = session_factory is None
    factory = session_factory or create_session_factory(runtime)
    try:
        with factory.begin() as session:
            _ensure_scopes(session, runtime)
            repo = MemoryRepository(session, runtime)
            existing_keys = {
                row.content
                for row in session.scalars(select(Memory).where(Memory.scope_id == DEMO_SCOPE_ID))
            }
            specs = [spec for spec in seed_specs() if spec.content not in existing_keys]
            if not specs:
                _ensure_demo_reviews(session, repo)
                return SeedSummary(
                    demo_scope_id=str(DEMO_SCOPE_ID),
                    live_scope_id=str(LIVE_SCOPE_ID),
                    inserted_memories=0,
                    inserted_events=0,
                    already_seeded=True,
                )
            scope = repo.require_scope(DEMO_SCOPE_ID)
            known: dict[str, Memory] = {}
            inserted_memories = 0
            inserted_events = 0
            with repo.mutation(scope_id=DEMO_SCOPE_ID, expected_revision=scope.revision):
                # Insert rows without superseded pointers first so version rows
                # can be listed in any catalog order. Pointers are linked below.
                for spec in specs:
                    count, events = _write_spec(session, repo, spec, known)
                    inserted_memories += count
                    inserted_events += events
                session.flush()
                for spec in specs:
                    if spec.superseded_by_key is not None:
                        target = known.get(spec.superseded_by_key)
                        if target is None:
                            target = session.scalar(
                                select(Memory).where(
                                    Memory.scope_id == DEMO_SCOPE_ID,
                                    Memory.id
                                    == next(
                                        candidate.id
                                        for candidate in seed_specs()
                                        if candidate.key == spec.superseded_by_key
                                    ),
                                )
                            )
                        if target is None:
                            raise RuntimeError(
                                f"missing superseded target {spec.superseded_by_key}"
                            )
                        row = known.get(spec.key) or session.get(Memory, spec.id)
                        if row is None:
                            raise RuntimeError(f"missing seeded row {spec.key}")
                        row.superseded_by_id = target.id
                session.flush()
            _ensure_demo_reviews(session, repo)
            return SeedSummary(
                demo_scope_id=str(DEMO_SCOPE_ID),
                live_scope_id=str(LIVE_SCOPE_ID),
                inserted_memories=inserted_memories,
                inserted_events=inserted_events,
                already_seeded=False,
            )
    finally:
        if owns_factory:
            bind = factory.kw.get("bind")
            dispose = getattr(bind, "dispose", None)
            if callable(dispose):
                dispose()


def refresh_demo_embeddings(
    settings: Settings | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
) -> int:
    """Refresh derived fixture vectors after a catalog-vector algorithm change."""

    runtime = settings or get_settings()
    owns_factory = session_factory is None
    factory = session_factory or create_session_factory(runtime)
    try:
        with factory.begin() as session:
            repo = MemoryRepository(session, runtime)
            scope = repo.require_scope(DEMO_SCOPE_ID)
            rows = list(session.scalars(select(Memory).where(Memory.scope_id == DEMO_SCOPE_ID)))
            changes: list[tuple[Memory, list[float]]] = []
            for row in rows:
                try:
                    vector = fixture_embeddings([row.content])[0]
                except ValueError:
                    continue
                current = list(row.embedding)
                same_vector = len(current) == len(vector) and all(
                    abs(float(left) - right) <= 1e-5
                    for left, right in zip(current, vector, strict=True)
                )
                if not same_vector or row.embedding_model != DEMO_MODEL:
                    changes.append((row, vector))
            if not changes:
                return 0
            with repo.mutation(scope_id=DEMO_SCOPE_ID, expected_revision=scope.revision):
                for row, vector in changes:
                    row.embedding = vector
                    row.embedding_model = DEMO_MODEL
                session.flush()
            return len(changes)
    finally:
        if owns_factory:
            bind = factory.kw.get("bind")
            dispose = getattr(bind, "dispose", None)
            if callable(dispose):
                dispose()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Load the authored MemoryOS demo catalog")
    parser.add_argument(
        "--refresh-embeddings",
        action="store_true",
        help="refresh derived fixture vectors for existing demo rows",
    )
    args = parser.parse_args(argv)
    if args.refresh_embeddings:
        print(json.dumps({"refreshed_embeddings": refresh_demo_embeddings()}, sort_keys=True))
    else:
        summary = seed_demo()
        print(json.dumps(asdict(summary), sort_keys=True))
