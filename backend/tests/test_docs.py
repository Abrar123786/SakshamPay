from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_openapi_and_swagger_ui_load(client):
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert "/health" in paths and "/api/v1/health" in paths

    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "swagger" in docs.text.lower()

    assert client.get("/redoc").status_code == 200


def test_docs_are_hidden_in_production():
    settings = Settings(_env_file=None, APP_ENV="production", JWT_SECRET_KEY="x" * 40)
    with TestClient(create_app(settings)) as prod_client:
        assert prod_client.get("/docs").status_code == 404
        assert prod_client.get("/openapi.json").status_code == 404
        assert prod_client.get("/health").status_code == 200
