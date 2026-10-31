"""Restrictive CORS: only the configured frontend origin(s), only the methods and headers the API uses."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import FRONTEND, make_settings


def preflight(client, origin, method="GET", headers="Authorization, Idempotency-Key"):
    return client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


def test_preflight_from_frontend_origin_is_allowed(client):
    response = preflight(client, FRONTEND)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed and "idempotency-key" in allowed


def test_simple_request_gets_cors_headers_without_credentials(client):
    response = client.get("/health", headers={"Origin": FRONTEND})
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert "x-request-id" in response.headers["access-control-expose-headers"].lower()
    assert "access-control-allow-credentials" not in response.headers  # bearer tokens, not cookies


def test_unknown_origin_is_refused(client):
    assert "access-control-allow-origin" not in client.get("/health", headers={"Origin": "https://evil.example"}).headers
    assert preflight(client, "https://evil.example").status_code == 400


def test_unlisted_method_and_header_are_refused(client):
    assert preflight(client, FRONTEND, method="PUT").status_code == 400
    assert preflight(client, FRONTEND, headers="X-Custom-Header").status_code == 400


def test_error_responses_are_readable_cross_origin(client):
    response = client.get("/does-not-exist", headers={"Origin": FRONTEND})
    assert response.status_code == 404
    assert response.headers["access-control-allow-origin"] == FRONTEND


def test_multiple_configured_origins_are_each_allowed():
    settings = make_settings(FRONTEND_ORIGIN=f"{FRONTEND},https://sakshampay.vercel.app")
    with TestClient(create_app(settings)) as client:
        for origin in (FRONTEND, "https://sakshampay.vercel.app"):
            assert client.get("/health", headers={"Origin": origin}).headers["access-control-allow-origin"] == origin
