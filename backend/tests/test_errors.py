from fastapi import Query

from app.core.exceptions import ConflictError
from tests.conftest import FRONTEND


def _assert_error_shape(body, code):
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert body["error"]["request_id"]


def test_unknown_route_returns_standard_404(client):
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    _assert_error_shape(response.json(), "NOT_FOUND")


def test_wrong_method_returns_standard_405(client):
    response = client.post("/health")
    assert response.status_code == 405
    _assert_error_shape(response.json(), "METHOD_NOT_ALLOWED")


def test_validation_error_returns_standard_422(app, client):
    @app.get("/_test/validate")
    def validate(amount: int = Query(gt=0)):
        return {"amount": amount}

    response = client.get("/_test/validate", params={"amount": -5})
    assert response.status_code == 422
    body = response.json()
    _assert_error_shape(body, "VALIDATION_ERROR")
    assert body["error"]["details"][0]["location"] == ["query", "amount"]


def test_app_error_maps_to_its_status_and_code(app, client):
    @app.get("/_test/conflict")
    def conflict():
        raise ConflictError("Transaction is already approved.", code="INVALID_STATE")

    response = client.get("/_test/conflict")
    assert response.status_code == 409
    _assert_error_shape(response.json(), "INVALID_STATE")


def test_unhandled_exception_returns_safe_500_with_cors(app, client):
    @app.get("/_test/crash")
    def crash():
        raise RuntimeError("secret internal detail")

    response = client.get("/_test/crash", headers={"Origin": FRONTEND})
    assert response.status_code == 500
    body = response.json()
    _assert_error_shape(body, "INTERNAL_ERROR")
    assert "secret internal detail" not in response.text
    # The browser must be able to read the error, so CORS headers are present
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert response.headers["x-request-id"] == body["error"]["request_id"]
