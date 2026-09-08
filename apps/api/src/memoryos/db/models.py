"""SQLAlchemy persistence models for MemoryOS.

The models deliberately keep the public Pydantic contracts out of the ORM.  A
memory row is one immutable version in a lineage; changes are represented by a
new row and an accompanying event.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    func,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from memoryos.domain.enums import (
    ExecutionMode,
    InteractionStatus,
    MemoryEventType,
    MemoryRelation,
    MemoryStatus,
    MemoryType,
)


def _enum_values(enum_type: type[Any]) -> list[str]:
    """Return stable values for a PostgreSQL enum built from a ``StrEnum``."""

    return [member.value for member in enum_type]


def _native_enum(enum_type: type[Any], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        values_callable=_enum_values,
        native_enum=True,
        validate_strings=True,
    )


class Base(DeclarativeBase):
    """Declarative metadata used by Alembic and local integration tests."""


class Scope(Base):
    __tablename__ = "scopes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (CheckConstraint("revision >= 0", name="ck_scopes_revision_nonnegative"),)


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    status: Mapped[InteractionStatus] = mapped_column(
        _native_enum(InteractionStatus, "interaction_status"),
        nullable=False,
    )
    mode: Mapped[ExecutionMode] = mapped_column(
        _native_enum(ExecutionMode, "execution_mode"),
        nullable=False,
    )
    decisions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sql_text("'[]'::jsonb"),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )
    trace: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("scope_id", "id", name="uq_interactions_scope_id"),
        UniqueConstraint(
            "scope_id",
            "idempotency_key",
            name="uq_interactions_scope_idempotency",
        ),
        ForeignKeyConstraint(
            ["scope_id"],
            ["scopes.id"],
            name="fk_interactions_scope",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status = 'preview' OR idempotency_key IS NOT NULL",
            name="ck_interactions_committed_idempotency",
        ),
    )


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    lineage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    memory_type: Mapped[MemoryType] = mapped_column(
        _native_enum(MemoryType, "memory_type"),
        nullable=False,
    )
    status: Mapped[MemoryStatus] = mapped_column(
        _native_enum(MemoryStatus, "memory_status"),
        nullable=False,
    )
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    context_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attribute_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    importance: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reinforcement_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("scope_id", "id", name="uq_memories_scope_id"),
        UniqueConstraint(
            "scope_id",
            "lineage_id",
            "version",
            name="uq_memories_lineage_version",
        ),
        ForeignKeyConstraint(
            ["scope_id"],
            ["scopes.id"],
            name="fk_memories_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["scope_id", "superseded_by_id"],
            ["memories.scope_id", "memories.id"],
            name="fk_memories_superseded_by_same_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version >= 1", name="ck_memories_version_positive"),
        CheckConstraint(
            "importance >= 0 AND importance <= 1",
            name="ck_memories_importance_unit_interval",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_memories_confidence_unit_interval",
        ),
        CheckConstraint(
            "reinforcement_count >= 0",
            name="ck_memories_reinforcement_nonnegative",
        ),
        Index(
            "ix_memories_scope_status_created",
            "scope_id",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "uq_memories_one_active_version",
            "scope_id",
            "lineage_id",
            unique=True,
            postgresql_where=sql_text("status = 'active'"),
        ),
    )


class MemoryEvent(Base):
    __tablename__ = "memory_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    memory_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    interaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_type: Mapped[MemoryEventType] = mapped_column(
        _native_enum(MemoryEventType, "memory_event_type"),
        nullable=False,
    )
    related_memory_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    evidence_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    reason_summary: Mapped[str] = mapped_column(Text, nullable=False)
    relation: Mapped[MemoryRelation | None] = mapped_column(
        _native_enum(MemoryRelation, "memory_relation"),
        nullable=True,
    )
    provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("scope_id", "id", name="uq_memory_events_scope_id"),
        ForeignKeyConstraint(
            ["scope_id"],
            ["scopes.id"],
            name="fk_memory_events_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["scope_id", "memory_id"],
            ["memories.scope_id", "memories.id"],
            name="fk_memory_events_memory_same_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["scope_id", "interaction_id"],
            ["interactions.scope_id", "interactions.id"],
            name="fk_memory_events_interaction_same_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["scope_id", "related_memory_id"],
            ["memories.scope_id", "memories.id"],
            name="fk_memory_events_related_memory_same_scope",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_memory_events_reinforcement_per_interaction",
            "scope_id",
            "interaction_id",
            "memory_id",
            unique=True,
            postgresql_where=and_(
                sql_text("event_type = 'reinforced'"),
                sql_text("interaction_id IS NOT NULL"),
            ),
        ),
        Index(
            "ix_memory_events_scope_memory_created",
            "scope_id",
            "memory_id",
            "created_at",
            "id",
        ),
    )


# ``JSON`` is imported intentionally for Alembic/SQLAlchemy dialect inspection in
# downstream tooling.  The runtime columns above use PostgreSQL JSONB.
__all__ = ["Base", "Interaction", "Memory", "MemoryEvent", "Scope"]
