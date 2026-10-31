"""Consistent error format, status codes and safe messages."""

import logging

from fastapi import Query
from sqlalchemy.exc import OperationalError

from app.core.exceptions import ConflictError
from tests.conftest import FRONTEND


def assert_error_shape(response, status_code, code):
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    return body


def test_unknown_route_returns_404(client):
    assert_error_shape(client.get("/does-not-exist"), 404, "NOT_FOUND")


def test_wrong_method_returns_405(client):
    assert_error_shape(client.post("/health"), 405, "METHOD_NOT_ALLOWED")


def test_validation_error_returns_422_with_details(app, client):
    @app.get("/_test/validate")
    def validate(amount: int = Query(gt=0)):
        return {"amount": amount}

    body = assert_error_shape(client.get("/_test/validate", params={"amount": -5}), 422, "VALIDATION_ERROR")
    assert body["error"]["details"][0]["location"] == ["query", "amount"]


def test_app_error_maps_to_its_status_and_code(app, client):
    @app.get("/_test/conflict")
    def conflict():
        raise ConflictError("Transaction is already approved.", code="INVALID_STATE")

    body = assert_error_shape(client.get("/_test/conflict"), 409, "INVALID_STATE")
    assert body["error"]["message"] == "Transaction is already approved."


def test_unhandled_exception_returns_safe_500_with_cors_and_is_logged(app, client, caplog):
    @app.get("/_test/crash")
    def crash():
        raise RuntimeError("secret internal detail")

    caplog.set_level(logging.ERROR)
    response = client.get("/_test/crash", headers={"Origin": FRONTEND})
    assert_error_shape(response, 500, "INTERNAL_ERROR")
    assert "secret internal detail" not in response.text
    assert response.headers["access-control-allow-origin"] == FRONTEND
    # Full traceback goes to the server log for debugging
    record = next(r for r in caplog.records if r.getMessage() == "Unhandled exception")
    assert record.exc_info and "secret internal detail" in caplog.text


def test_database_errors_become_safe_503(app, client):
    @app.get("/_test/db-down")
    def db_down():
        raise OperationalError("SELECT 1", {}, Exception('connection to server at "10.0.0.5" failed'))

    response = client.get("/_test/db-down")
    assert_error_shape(response, 503, "DATABASE_UNAVAILABLE")
    assert "10.0.0.5" not in response.text and "SELECT" not in response.text


def test_oversized_body_is_rejected_with_413(client):
    response = client.post("/health", content=b"x" * 2_000_000, headers={"Content-Type": "application/json"})
    assert_error_shape(response, 413, "PAYLOAD_TOO_LARGE")


def test_invalid_content_length_is_rejected_with_400(client):
    response = client.post("/health", headers={"Content-Length": "abc"})
    assert_error_shape(response, 400, "BAD_REQUEST")
