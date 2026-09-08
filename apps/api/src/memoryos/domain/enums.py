"""Domain values shared by persistence, policy, and transport layers."""

from enum import StrEnum


class MemoryType(StrEnum):
    PREFERENCE = "preference"
    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    PROCEDURAL = "procedural"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    FORGOTTEN = "forgotten"


class ExecutionMode(StrEnum):
    DEMO = "demo"
    LIVE = "live"


class InteractionStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PREVIEW = "preview"
    FAILED = "failed"


class IngestDecisionType(StrEnum):
    CREATED = "created"
    REINFORCED = "reinforced"
    SUPERSEDED = "superseded"
    DISPUTED = "disputed"
    SKIPPED = "skipped"
    REJECTED = "rejected"


class MemoryRelation(StrEnum):
    NEW = "new"
    REINFORCE = "reinforce"
    SUPERSEDE = "supersede"
    DISPUTE = "dispute"
    SKIP = "skip"


class MemoryEventType(StrEnum):
    CREATED = "created"
    REINFORCED = "reinforced"
    SUPERSEDED = "superseded"
    DISPUTED = "disputed"
    FORGOTTEN = "forgotten"
    RESOLVED = "resolved"
    EXPIRED = "expired"

