"""Versioned routing: everything in api_router is served under API_V1_PREFIX only."""

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import create_app
from tests.conftest import make_settings

SYSTEM_PATHS = {"/", "/health", "/health/ready"}


@pytest.fixture
def probe_router(monkeypatch):
    """Stand-in for a future feature router, mounted through the real api_router path."""
    router = APIRouter()

    @router.get("/probe")
    def probe():
        return {"ok": True}

    monkeypatch.setattr(main_module, "api_router", router)
    return router


def test_feature_routes_are_served_under_api_v1(probe_router):
    with TestClient(create_app(make_settings())) as client:
        assert client.get("/api/v1/probe").json() == {"ok": True}
        assert client.get("/probe").status_code == 404


def test_prefix_comes_from_settings(probe_router):
    with TestClient(create_app(make_settings(API_V1_PREFIX="/api/v2"))) as client:
        assert client.get("/api/v2/probe").status_code == 200
        assert client.get("/api/v1/probe").status_code == 404


def test_openapi_lists_only_real_routes(client):
    paths = set(client.get("/openapi.json").json()["paths"])
    # No business endpoints exist yet; every path is either a system path or versioned.
    assert paths == SYSTEM_PATHS
    assert all(p in SYSTEM_PATHS or p.startswith("/api/v1/") for p in paths)


def test_unknown_versioned_route_returns_standard_404(client):
    response = client.get("/api/v1/transactions")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
