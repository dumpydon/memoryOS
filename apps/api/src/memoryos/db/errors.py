"""Exceptions raised by the persistence boundary."""

from __future__ import annotations

from uuid import UUID


class PersistenceError(RuntimeError):
    """Base class for expected repository failures."""


class ScopeNotFoundError(PersistenceError):
    def __init__(self, scope_id: UUID) -> None:
        super().__init__(f"scope {scope_id} does not exist")
        self.scope_id = scope_id


class ScopeRevisionConflict(PersistenceError):
    """The caller's scope snapshot is stale."""

    def __init__(self, scope_id: UUID, expected: int, actual: int) -> None:
        super().__init__(f"scope {scope_id} revision conflict: expected {expected}, found {actual}")
        self.scope_id = scope_id
        self.expected = expected
        self.actual = actual


class IdempotencyConflict(PersistenceError):
    """An idempotency key was reused with different request content."""

    def __init__(self, scope_id: UUID, idempotency_key: str) -> None:
        super().__init__(
            f"idempotency key {idempotency_key!r} is already used by a different request"
        )
        self.scope_id = scope_id
        self.idempotency_key = idempotency_key


class DuplicateReinforcement(PersistenceError):
    """An interaction has already reinforced the same memory."""

    def __init__(self, scope_id: UUID, interaction_id: UUID, memory_id: UUID) -> None:
        super().__init__(f"interaction {interaction_id} already reinforced memory {memory_id}")
        self.scope_id = scope_id
        self.interaction_id = interaction_id
        self.memory_id = memory_id


class InvalidEmbedding(PersistenceError, ValueError):
    """A vector does not satisfy the MemoryOS pgvector contract."""


__all__ = [
    "DuplicateReinforcement",
    "IdempotencyConflict",
    "InvalidEmbedding",
    "PersistenceError",
    "ScopeNotFoundError",
    "ScopeRevisionConflict",
]
