"""Add explainability and durable review records for MemoryOS Phase 2."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_phase2_engine"
down_revision: str | None = "0001_initial_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column(
            "why",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_table(
        "memory_reviews",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scope_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("candidate", JSONB(), nullable=False),
        sa.Column("existing_memory", JSONB(), nullable=True),
        sa.Column(
            "source_memories",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "source_memory_ids",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "proposed_relation",
            PgEnum(name="memory_relation", create_type=False),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_excerpt", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("reason_summary", sa.Text(), nullable=False),
        sa.Column("resolution", sa.String(length=32), nullable=True),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.Column("memory_id", sa.UUID(), nullable=True),
        sa.Column("existing_memory_id", sa.UUID(), nullable=True),
        sa.Column(
            "mode",
            PgEnum(name="execution_mode", create_type=False),
            server_default=sa.text("'demo'"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["scope_id"], ["scopes.id"], name="fk_memory_reviews_scope", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["scope_id", "memory_id"],
            ["memories.scope_id", "memories.id"],
            name="fk_memory_reviews_memory_same_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scope_id", "existing_memory_id"],
            ["memories.scope_id", "memories.id"],
            name="fk_memory_reviews_existing_memory_same_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "kind IN ('conflict', 'consolidation')", name="ck_memory_reviews_kind"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved')", name="ck_memory_reviews_status"
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_memory_reviews_confidence_unit_interval",
        ),
        sa.UniqueConstraint("scope_id", "id", name="uq_memory_reviews_scope_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_reviews_scope_status_created",
        "memory_reviews",
        ["scope_id", "status", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_reviews_scope_status_created", table_name="memory_reviews")
    op.drop_table("memory_reviews")
    op.drop_column("memories", "why")
