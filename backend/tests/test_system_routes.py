"""Unversioned system endpoints: /, /health, /health/ready."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_production_settings

HEALTH_BODY = {"status": "healthy", "application": "SakshamPay", "version": "1.0.0"}


def test_root_returns_service_information(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "application": "SakshamPay",
        "version": "1.0.0",
        "api_base": "/api/v1",
        "health": "/health",
        "readiness": "/health/ready",
        "docs": "/docs",
    }


def test_root_hides_docs_link_in_production():
    with TestClient(create_app(make_production_settings(DB_CONNECT_TIMEOUT_SECONDS=1))) as client:
        assert client.get("/").json()["docs"] is None


def test_health_returns_expected_body(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == HEALTH_BODY


def test_responses_carry_security_headers(client):
    # Carried over from the P-2 test_health.py, which was the only place these were asserted
    for path in ("/", "/health", "/does-not-exist"):
        headers = client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"


def test_health_is_not_duplicated_under_api_prefix(client):
    assert client.get("/api/v1/health").status_code == 404


def test_health_does_not_depend_on_database(unreachable_db_client):
    assert unreachable_db_client.get("/health").json() == HEALTH_BODY


def test_readiness_without_database_configured(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == {"status": "not_configured", "latency_ms": None}


def test_readiness_with_unreachable_database_is_503(unreachable_db_client):
    response = unreachable_db_client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"]["status"] == "unavailable"
    # No connection details leak into the response
    assert "127.0.0.1" not in response.text and "password" not in response.text
