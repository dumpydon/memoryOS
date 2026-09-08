"""Initial MemoryOS persistence schema.

Revision ID: 0001_initial_persistence
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001_initial_persistence"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, values: list[str]) -> None:
    op.execute(
        sa.text(
            "CREATE TYPE "
            + name
            + " AS ENUM ("
            + ", ".join("'" + value + "'" for value in values)
            + ")"
        )
    )


def upgrade() -> None:
    # pgvector is an explicit schema dependency.  Keeping this in the migration
    # makes fresh Postgres 17 databases reproducible while remaining idempotent.
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    _enum(
        "interaction_status",
        ["received", "processing", "completed", "preview", "failed"],
    )
    _enum("execution_mode", ["demo", "live"])
    _enum("memory_type", ["preference", "semantic", "episodic", "procedural"])
    _enum("memory_status", ["active", "disputed", "superseded", "forgotten"])
    _enum(
        "memory_event_type",
        ["created", "reinforced", "superseded", "disputed", "forgotten", "resolved", "expired"],
    )
    _enum("memory_relation", ["new", "reinforce", "supersede", "dispute", "skip"])

    op.create_table(
        "scopes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("revision >= 0", name="ck_scopes_revision_nonnegative"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "interactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scope_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("status", PgEnum(name="interaction_status", create_type=False), nullable=False),
        sa.Column("mode", PgEnum(name="execution_mode", create_type=False), nullable=False),
        sa.Column(
            "decisions",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "trace",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["scope_id"], ["scopes.id"], name="fk_interactions_scope", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("scope_id", "id", name="uq_interactions_scope_id"),
        sa.UniqueConstraint(
            "scope_id", "idempotency_key", name="uq_interactions_scope_idempotency"
        ),
        sa.CheckConstraint(
            "status = 'preview' OR idempotency_key IS NOT NULL",
            name="ck_interactions_committed_idempotency",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "memories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scope_id", sa.UUID(), nullable=False),
        sa.Column("lineage_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("memory_type", PgEnum(name="memory_type", create_type=False), nullable=False),
        sa.Column("status", PgEnum(name="memory_status", create_type=False), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("context_key", sa.String(length=255), nullable=True),
        sa.Column("attribute_key", sa.String(length=255), nullable=True),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reinforcement_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["scope_id"], ["scopes.id"], name="fk_memories_scope", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["scope_id", "superseded_by_id"],
            ["memories.scope_id", "memories.id"],
            name="fk_memories_superseded_by_same_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("scope_id", "id", name="uq_memories_scope_id"),
        sa.UniqueConstraint(
            "scope_id", "lineage_id", "version", name="uq_memories_lineage_version"
        ),
        sa.CheckConstraint("version >= 1", name="ck_memories_version_positive"),
        sa.CheckConstraint(
            "importance >= 0 AND importance <= 1", name="ck_memories_importance_unit_interval"
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_memories_confidence_unit_interval"
        ),
        sa.CheckConstraint(
            "reinforcement_count >= 0", name="ck_memories_reinforcement_nonnegative"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memories_scope_status_created",
        "memories",
        ["scope_id", "status", "created_at", "id"],
    )
    op.create_index(
        "uq_memories_one_active_version",
        "memories",
        ["scope_id", "lineage_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "memory_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scope_id", sa.UUID(), nullable=False),
        sa.Column("memory_id", sa.UUID(), nullable=False),
        sa.Column("interaction_id", sa.UUID(), nullable=True),
        sa.Column(
            "event_type", PgEnum(name="memory_event_type", create_type=False), nullable=False
        ),
        sa.Column("related_memory_id", sa.UUID(), nullable=True),
        sa.Column("evidence_excerpt", sa.Text(), nullable=True),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("reason_summary", sa.Text(), nullable=False),
        sa.Column("relation", PgEnum(name="memory_relation", create_type=False), nullable=True),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column("before", JSONB(), nullable=True),
        sa.Column("after", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["scope_id"], ["scopes.id"], name="fk_memory_events_scope", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["scope_id", "memory_id"],
            ["memories.scope_id", "memories.id"],
            name="fk_memory_events_memory_same_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scope_id", "interaction_id"],
            ["interactions.scope_id", "interactions.id"],
            name="fk_memory_events_interaction_same_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scope_id", "related_memory_id"],
            ["memories.scope_id", "memories.id"],
            name="fk_memory_events_related_memory_same_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("scope_id", "id", name="uq_memory_events_scope_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_memory_events_reinforcement_per_interaction",
        "memory_events",
        ["scope_id", "interaction_id", "memory_id"],
        unique=True,
        postgresql_where=sa.text("event_type = 'reinforced' AND interaction_id IS NOT NULL"),
    )
    op.create_index(
        "ix_memory_events_scope_memory_created",
        "memory_events",
        ["scope_id", "memory_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_events_scope_memory_created", table_name="memory_events")
    op.drop_index("uq_memory_events_reinforcement_per_interaction", table_name="memory_events")
    op.drop_table("memory_events")
    op.drop_index("uq_memories_one_active_version", table_name="memories")
    op.drop_index("ix_memories_scope_status_created", table_name="memories")
    op.drop_table("memories")
    op.drop_table("interactions")
    op.drop_table("scopes")
    op.execute(sa.text("DROP TYPE memory_relation"))
    op.execute(sa.text("DROP TYPE memory_event_type"))
    op.execute(sa.text("DROP TYPE memory_status"))
    op.execute(sa.text("DROP TYPE memory_type"))
    op.execute(sa.text("DROP TYPE execution_mode"))
    op.execute(sa.text("DROP TYPE interaction_status"))
