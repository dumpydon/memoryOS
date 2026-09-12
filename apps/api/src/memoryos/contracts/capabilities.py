"""Non-secret configuration readiness for the dashboard."""

from memoryos.contracts.common import ContractModel


class CapabilitiesResponse(ContractModel):
    live_ingestion_available: bool
    live_recall_available: bool
    reason: str | None = None
    structured_model: str
    embedding_model: str
