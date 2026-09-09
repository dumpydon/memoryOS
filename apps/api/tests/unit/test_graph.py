from collections.abc import Callable

from memoryos.graph.factory import build_ingestion_graph
from memoryos.graph.state import GraphState


def test_empty_extraction_skips_embedding_and_relation_stages() -> None:
    visited: list[str] = []

    def node(name: str) -> Callable[[GraphState], GraphState]:
        def run(state: GraphState) -> GraphState:
            visited.append(name)
            return {"candidates": []} if name == "extract" else {}

        return run

    graph = build_ingestion_graph(
        nodes={
            name: node(name)
            for name in (
                "extract",
                "embed",
                "find_related",
                "assess_relations",
                "validate_plan",
                "persist",
            )
        }
    )
    graph.invoke({"stage_timings": {}}, config={"recursion_limit": 12})
    assert visited == ["extract", "validate_plan", "persist"]


def test_related_snapshot_without_rows_skips_second_structured_call() -> None:
    visited: list[str] = []

    def extract(state: GraphState) -> GraphState:
        visited.append("extract")
        return {"candidates": ["candidate"]}

    def embed(state: GraphState) -> GraphState:
        visited.append("embed")
        return {"candidate_embeddings": [[1.0]]}

    def find_related(state: GraphState) -> GraphState:
        visited.append("find_related")
        return {"related_memories": {"candidate": []}}

    def mark(name: str) -> Callable[[GraphState], GraphState]:
        def run(state: GraphState) -> GraphState:
            visited.append(name)
            return {}

        return run

    graph = build_ingestion_graph(
        nodes={
            "extract": extract,
            "embed": embed,
            "find_related": find_related,
            "assess_relations": mark("assess_relations"),
            "validate_plan": mark("validate_plan"),
            "persist": mark("persist"),
        }
    )
    graph.invoke({"stage_timings": {}}, config={"recursion_limit": 12})
    assert visited == ["extract", "embed", "find_related", "validate_plan", "persist"]
