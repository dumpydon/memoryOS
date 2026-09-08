"""Database adapter boundaries and SQLAlchemy persistence primitives."""

from memoryos.db.errors import (
    DuplicateReinforcement,
    IdempotencyConflict,
    InvalidEmbedding,
    PersistenceError,
    ScopeNotFoundError,
    ScopeRevisionConflict,
)
from memoryos.db.models import Base, Interaction, Memory, MemoryEvent, Scope
from memoryos.db.repositories import (
    InteractionResult,
    MemoryRepository,
    RecallCandidate,
    RelatedCandidate,
    ScopeResult,
    SqlAlchemyMemoryRepository,
    StoredMemory,
)
from memoryos.db.transactions import ScopeRevision, scope_mutation, scope_revision_transaction

__all__ = [
    "Base",
    "DuplicateReinforcement",
    "IdempotencyConflict",
    "Interaction",
    "InteractionResult",
    "InvalidEmbedding",
    "Memory",
    "MemoryEvent",
    "MemoryRepository",
    "PersistenceError",
    "RecallCandidate",
    "RelatedCandidate",
    "Scope",
    "ScopeNotFoundError",
    "ScopeRevision",
    "ScopeRevisionConflict",
    "ScopeResult",
    "SqlAlchemyMemoryRepository",
    "StoredMemory",
    "scope_mutation",
    "scope_revision_transaction",
]
