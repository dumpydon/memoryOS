"""Transport contract checks shared by REST and MCP adapters."""

from __future__ import annotations

from fastapi.testclient import TestClient

from memoryos.config import Settings
from memoryos.main import create_app
from memoryos.seed.catalog import DEMO_SCOPE_ID, get_catalog


def test_capabilities_report_configuration_without_disclosing_credentials() -> None:
    for key, available in ((None, False), ("test-secret-never-return", True)):
        settings = Settings(openai_api_key=key)
        with TestClient(create_app(settings)) as client:
            response = client.get("/v1/capabilities")
        assert response.status_code == 200
        payload = response.json()
        assert payload["live_ingestion_available"] is available
        assert payload["live_recall_available"] is available
        assert "test-secret-never-return" not in response.text
        assert (payload["reason"] is None) is available


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


def test_review_mutations_require_owner_and_private_reviews_are_scoped() -> None:
    with TestClient(create_app()) as client:
        resolve = client.post(
            "/v1/reviews/00000000-0000-0000-0000-000000000010/resolve",
            params={"scope_id": str(DEMO_SCOPE_ID)},
            json={"action": "use_new"},
        )
        propose = client.post(
            "/v1/consolidations/propose",
            json={
                "scope_id": str(DEMO_SCOPE_ID),
                "source_memory_ids": [
                    "00000000-0000-0000-0000-000000000011",
                    "00000000-0000-0000-0000-000000000012",
                    "00000000-0000-0000-0000-000000000013",
                ],
            },
        )
        private_reviews = client.get(
            "/v1/reviews", params={"scope_id": "00000000-0000-0000-0000-000000000002"}
        )
    assert resolve.status_code == propose.status_code == 401
    assert private_reviews.status_code == 403
    assert private_reviews.json()["code"] == "scope_forbidden"
