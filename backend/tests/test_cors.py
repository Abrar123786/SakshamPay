from tests.conftest import FRONTEND


def test_preflight_from_frontend_origin_is_allowed(client):
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": FRONTEND,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization, Idempotency-Key",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed and "idempotency-key" in allowed


def test_simple_request_from_frontend_origin_gets_cors_headers(client):
    response = client.get("/api/v1/health", headers={"Origin": FRONTEND})
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert "x-request-id" in response.headers["access-control-expose-headers"].lower()
    # Bearer tokens are used, not cookies
    assert "access-control-allow-credentials" not in response.headers


def test_unknown_origin_is_not_allowed(client):
    response = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers

    preflight = client.options(
        "/api/v1/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 400
