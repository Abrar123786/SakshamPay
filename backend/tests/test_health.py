import pytest

EXPECTED = {"status": "healthy", "application": "SakshamPay", "version": "1.0.0"}


@pytest.mark.parametrize("path", ["/health", "/api/v1/health"])
def test_health_returns_expected_body(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == EXPECTED


def test_health_sets_request_id_and_security_headers(client):
    response = client.get("/health")
    assert len(response.headers["x-request-id"]) >= 8
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_valid_incoming_request_id_is_echoed(client):
    response = client.get("/health", headers={"X-Request-ID": "test-request-0001"})
    assert response.headers["x-request-id"] == "test-request-0001"


def test_malformed_incoming_request_id_is_replaced(client):
    response = client.get("/health", headers={"X-Request-ID": "bad id <script>"})
    assert response.headers["x-request-id"] != "bad id <script>"
