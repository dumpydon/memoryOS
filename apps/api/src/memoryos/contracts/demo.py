"""Public, finite demo catalog. These are fixtures, never live model claims."""

from uuid import UUID

from memoryos.contracts.common import ContractModel


class DemoScenario(ContractModel):
    id: str
    title: str
    description: str
    text: str
    expected_outcome: str


class DemoQuery(ContractModel):
    id: str
    title: str
    query: str


class DemoCatalogResponse(ContractModel):
    scope_id: UUID
    embedding_model: str
    notice: str
    scenarios: list[DemoScenario]
    queries: list[DemoQuery]
