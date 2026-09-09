"""Bounded LangGraph construction for synchronous ingestion."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from time import perf_counter
from typing import Any, cast

from memoryos.contracts.common import TraceStep
from memoryos.contracts.ingestion import IngestInteractionResponse
from memoryos.domain.enums import InteractionStatus
from memoryos.graph.state import GraphState

GraphNode = Callable[[GraphState], GraphState]
INGESTION_STAGES = (
    "extract",
    "embed",
    "find_related",
    "assess_relations",
    "validate_plan",
    "persist",
)


def _timed_node(name: str, node: GraphNode) -> GraphNode:
    def run(state: GraphState) -> GraphState:
        started = perf_counter()
        try:
            update = node(state)
        except Exception:
            timings = dict(state.get("stage_timings", {}))
            timings[name] = (perf_counter() - started) * 1000
            state["stage_timings"] = timings
            raise
        result = cast(GraphState, dict(state))
        result.update(update)
        timings = dict(result.get("stage_timings", {}))
        timings[name] = (perf_counter() - started) * 1000
        result["stage_timings"] = timings
        response = result.get("response")
        # A committed response must retain the trace stored in its atomic write,
        # so an idempotent replay returns exactly the same result.
        if (
            isinstance(response, IngestInteractionResponse)
            and response.status is not InteractionStatus.COMPLETED
        ):
            response = response.model_copy(
                update={
                    "trace": response.trace.model_copy(
                        update={
                            "steps": [
                                TraceStep(
                                    node=stage,
                                    duration_ms=duration,
                                    status="completed",
                                )
                                for stage, duration in timings.items()
                            ]
                        }
                    )
                }
            )
            result["response"] = response
        return result

    return run


def build_ingestion_graph(
    *,
    nodes: Mapping[str, GraphNode] | None = None,
) -> Any:
    """Compile the six bounded ingestion stages with conditional skips.

    Provider and persistence dependencies are supplied as node closures by the
    service. Keeping construction here makes the execution order and branch
    bounds visible and lets unit tests inject deterministic nodes.
    """

    if nodes is None or set(nodes) != set(INGESTION_STAGES):
        missing = sorted(set(INGESTION_STAGES) - set(nodes or {}))
        extra = sorted(set(nodes or {}) - set(INGESTION_STAGES))
        detail = f"missing={missing!r}, extra={extra!r}"
        raise ValueError(f"ingestion graph requires exactly six stages ({detail})")
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject
        raise RuntimeError("langgraph is required to build the ingestion graph") from exc

    graph = StateGraph(GraphState)
    for name in INGESTION_STAGES:
        graph.add_node(name, cast(Any, _timed_node(name, nodes[name])))
    graph.add_edge(START, "extract")
    graph.add_conditional_edges(
        "extract",
        lambda state: "embed" if state.get("candidates") else "validate_plan",
        {"embed": "embed", "validate_plan": "validate_plan"},
    )
    graph.add_edge("embed", "find_related")
    graph.add_conditional_edges(
        "find_related",
        lambda state: (
            "assess_relations"
            if any(state.get("related_memories", {}).values())
            else "validate_plan"
        ),
        {
            "assess_relations": "assess_relations",
            "validate_plan": "validate_plan",
        },
    )
    graph.add_edge("assess_relations", "validate_plan")
    graph.add_edge("validate_plan", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


__all__ = ["GraphNode", "INGESTION_STAGES", "build_ingestion_graph"]
