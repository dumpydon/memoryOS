"""Provider construction shared by ingestion and query workers."""

from __future__ import annotations

from memoryos.config import Settings
from memoryos.domain.enums import ExecutionMode
from memoryos.providers.demo import DemoEmbeddingProvider, DemoStructuredProvider
from memoryos.providers.openai import OpenAIEmbeddingProvider, OpenAIProvider


def _mode(value: ExecutionMode | str) -> ExecutionMode:
    try:
        return value if isinstance(value, ExecutionMode) else ExecutionMode(value)
    except ValueError as exc:
        raise ValueError(f"unsupported execution mode: {value!r}") from exc


def make_embedding_provider(
    mode: ExecutionMode | str,
    settings: Settings,
) -> DemoEmbeddingProvider | OpenAIEmbeddingProvider:
    """Build the embedding provider for one explicit execution mode."""

    selected = _mode(mode)
    if selected is ExecutionMode.DEMO:
        return DemoEmbeddingProvider(settings)
    return OpenAIEmbeddingProvider(settings)


def make_structured_provider(
    mode: ExecutionMode | str,
    settings: Settings,
) -> DemoStructuredProvider | OpenAIProvider:
    """Build the structured extraction/relation provider for one mode."""

    selected = _mode(mode)
    if selected is ExecutionMode.DEMO:
        return DemoStructuredProvider(settings)
    return OpenAIProvider(settings)


__all__ = ["make_embedding_provider", "make_structured_provider"]
