from datetime import datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from memoryos.contracts.ingestion import IngestInteractionRequest
from memoryos.contracts.recall import RecallScoreBreakdown
from memoryos.domain.enums import ExecutionMode


def test_ingest_text_is_normalized() -> None:
    request = IngestInteractionRequest(
        scope_id=UUID("00000000-0000-0000-0000-000000000001"),
        text="  concise   answers  ",
        mode=ExecutionMode.DEMO,
    )
    assert request.text == "concise answers"


def test_ingest_rejects_naive_occurred_at() -> None:
    with pytest.raises(ValidationError, match="must include a timezone"):
        IngestInteractionRequest(
            scope_id=UUID("00000000-0000-0000-0000-000000000001"),
            text="a fact",
            occurred_at=datetime(2026, 1, 1),
        )


def test_score_breakdown_preserves_raw_negative_similarity() -> None:
    score = RecallScoreBreakdown(
        policy_version="memoryos-v1",
        raw_similarity=-0.1,
        similarity=0,
        importance=0,
        recency=0,
        reinforcement=0,
        confidence=0,
        weighted_similarity=0,
        weighted_importance=0,
        weighted_recency=0,
        weighted_reinforcement=0,
        weighted_confidence=0,
        total=0,
        days_since_confirmation=0,
        half_life_days=180,
    )
    assert score.raw_similarity == -0.1
