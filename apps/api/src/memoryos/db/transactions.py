"""Small transaction helpers shared by mutation workers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from memoryos.db.errors import ScopeNotFoundError, ScopeRevisionConflict
from memoryos.db.models import Scope


@dataclass(frozen=True, slots=True)
class ScopeRevision:
    """The locked scope revision before and after one mutation batch."""

    scope_id: UUID
    previous: int
    current: int


@contextmanager
def scope_revision_transaction(
    session: Session,
    *,
    scope_id: UUID,
    expected_revision: int,
) -> Iterator[ScopeRevision]:
    """Lock a scope, validate its revision, and reserve the next revision.

    The helper intentionally does not commit.  The caller owns the surrounding
    transaction and must perform all database writes inside this context.  Provider
    calls must happen before entering it; a provider failure therefore cannot leave
    a partially advanced scope revision.
    """

    scope = session.scalar(select(Scope).where(Scope.id == scope_id).with_for_update())
    if scope is None:
        raise ScopeNotFoundError(scope_id)
    if scope.revision != expected_revision:
        raise ScopeRevisionConflict(scope_id, expected_revision, scope.revision)

    previous = scope.revision
    scope.revision = previous + 1
    # Flush while the lock is held so a constraint failure aborts this transaction
    # before any caller-visible result is returned.
    session.flush()
    try:
        yield ScopeRevision(scope_id=scope_id, previous=previous, current=scope.revision)
    except Exception:
        # The session's outer transaction manager performs the rollback.  Expire the
        # object now so a caller that catches an exception cannot observe a stale
        # in-memory revision and accidentally reuse it.
        session.expire(scope)
        raise


# A descriptive alias used by workers that prefer the word "mutation".
scope_mutation = scope_revision_transaction


__all__ = [
    "ScopeRevision",
    "scope_mutation",
    "scope_revision_transaction",
]
