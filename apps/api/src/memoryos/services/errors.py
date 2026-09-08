"""Errors shared by services and both transport adapters."""


class ServiceError(Exception):
    """A safe user-facing error; never contains credentials or provider payloads."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


ERROR_HTTP_STATUS: dict[str, int] = {
    "not_found": 404,
    "unauthorized": 401,
    "forbidden": 403,
    "invalid_request": 422,
    "unsupported_demo_input": 422,
    "embedding_model_mismatch": 409,
    "idempotency_conflict": 409,
    "revision_conflict": 409,
    "interaction_in_progress": 409,
    "provider_unavailable": 503,
    "provider_timeout": 504,
    "provider_output_invalid": 502,
}
