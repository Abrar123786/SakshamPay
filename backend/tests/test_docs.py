"""Interactive API documentation."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_production_settings


def test_swagger_redoc_and_openapi_load(client):
    assert client.get("/openapi.json").status_code == 200
    docs = client.get("/docs")
    assert docs.status_code == 200 and "swagger" in docs.text.lower()
    assert client.get("/redoc").status_code == 200


def test_openapi_documents_readiness_503(client):
    responses = client.get("/openapi.json").json()["paths"]["/health/ready"]["get"]["responses"]
    assert {"200", "503"} <= set(responses)


def test_docs_are_hidden_in_production():
    with TestClient(create_app(make_production_settings(DB_CONNECT_TIMEOUT_SECONDS=1))) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/health").status_code == 200
