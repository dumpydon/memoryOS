"""Transport contract checks shared by REST and MCP adapters."""

from __future__ import annotations

from fastapi.testclient import TestClient

from memoryos.main import create_app
from memoryos.seed.catalog import DEMO_SCOPE_ID, get_catalog


def test_public_catalog_is_finite_and_fixture_labelled() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/v1/demo/scenarios")
    assert response.status_code == 200
    payload = response.json()
    assert payload["scope_id"] == str(DEMO_SCOPE_ID)
    assert payload["embedding_model"] == "demo-fixture-v1"
    assert payload["notice"] == get_catalog().notice
    assert payload["scenarios"]
    assert payload["queries"]


def test_public_mutation_and_unsupported_recall_use_error_envelope() -> None:
    scope_id = str(DEMO_SCOPE_ID)
    with TestClient(create_app()) as client:
        forget = client.post(
            "/v1/memories/00000000-0000-0000-0000-000000000001/forget",
            params={"scope_id": scope_id},
            json={},
        )
        recall = client.post(
            "/v1/recall",
            json={"scope_id": scope_id, "query": "not in the fixture catalog"},
        )
    assert forget.status_code == 401
    assert recall.status_code == 422
    for response, code in ((forget, "auth_required"), (recall, "demo_input_not_allowed")):
        body = response.json()
        assert body["code"] == code
        assert body["request_id"]
        assert set(body) == {"code", "message", "request_id", "retryable"}
