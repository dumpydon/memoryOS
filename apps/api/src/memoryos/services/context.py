"""Recall -> bounded contextual data -> one response. No writes or new ranking."""

import json
from collections.abc import Callable
from typing import Any

from memoryos.config import Settings
from memoryos.contracts.context import ContextMemory, ContextRequest, ContextResponse
from memoryos.contracts.recall import RecallRequest, RecallResponse
from memoryos.domain.enums import ExecutionMode, MemoryStatus
from memoryos.providers.errors import (
    ProviderOutputInvalid,
    ProviderTimeout,
    ProviderUnavailable,
    UnsupportedDemoInput,
)
from memoryos.providers.factory import make_structured_provider
from memoryos.seed.context import DEMO_CONTEXT_REQUEST
from memoryos.services.errors import ServiceError
from memoryos.services.query import MemoryQueryService

MAX_CONTEXT_CHARS = 6_000
MAX_MEMORY_CHARS = 1_500


def build_memory_context(recalled: RecallResponse) -> tuple[str, list[ContextMemory]]:
    """Preserve recall order; return exactly the complete statements supplied."""
    data: list[dict[str, str]] = []
    used: list[ContextMemory] = []
    seen = set()
    for item in recalled.items:
        memory = item.memory
        if (
            memory.status is not MemoryStatus.ACTIVE
            or memory.scope_id != recalled.scope_id
            or memory.effective_at > recalled.evaluated_at
            or (memory.expires_at is not None and memory.expires_at <= recalled.evaluated_at)
            or memory.id in seen
            or not memory.content.strip()
            or len(memory.content) > MAX_MEMORY_CHARS
        ):
            continue
        entry = {"content": memory.content}
        if memory.context_key:
            entry["context"] = memory.context_key[:200]
        if len(json.dumps([*data, entry], ensure_ascii=False)) > MAX_CONTEXT_CHARS:
            continue
        data.append(entry)
        seen.add(memory.id)
        used.append(
            ContextMemory(
                id=memory.id,
                content=memory.content,
                memory_type=memory.memory_type,
                context_key=memory.context_key,
            )
        )
        if len(used) == 5:
            break
    return json.dumps(data, ensure_ascii=False), used


class RecallContextService:
    def __init__(
        self,
        settings: Settings,
        query: MemoryQueryService,
        *,
        provider_factory: Callable[[ExecutionMode, Settings], Any] = make_structured_provider,
    ):
        self.settings = settings
        self.query = query
        self.provider_factory = provider_factory

    def answer(self, request: ContextRequest) -> ContextResponse:
        if (
            request.mode is ExecutionMode.DEMO
            and request.query.casefold() != DEMO_CONTEXT_REQUEST.casefold()
        ):
            raise ServiceError(
                "demo_input_not_allowed", "Demo context accepts the binary search example."
            )
        recalled = self.query.recall(
            RecallRequest(
                scope_id=request.scope_id,
                query=request.query,
                mode=request.mode,
                limit=request.limit,
            )
        )
        context, used = build_memory_context(recalled)
        try:
            provider = self.provider_factory(request.mode, self.settings)
            answer = provider.generate_answer(query=request.query, memory_context=context)
        except UnsupportedDemoInput as exc:
            raise ServiceError(
                "demo_input_not_allowed", "This recorded demo is unavailable."
            ) from exc
        except ProviderTimeout as exc:
            raise ServiceError("provider_timeout", str(exc), retryable=True) from exc
        except ProviderOutputInvalid as exc:
            raise ServiceError("provider_output_invalid", str(exc)) from exc
        except ProviderUnavailable as exc:
            raise ServiceError("provider_unavailable", str(exc), retryable=True) from exc
        if not isinstance(answer, str) or not answer.strip():
            raise ServiceError("provider_output_invalid", "The provider returned no answer.")
        return ContextResponse(
            query=request.query,
            answer=answer,
            memories_used=used,
            mode=request.mode,
            model=provider.model_name,
        )
