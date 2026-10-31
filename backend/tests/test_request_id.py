"""Request ID generation and propagation."""

import logging
import re


def test_request_id_is_generated(client):
    request_id = client.get("/health").headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)


def test_each_request_gets_a_new_id(client):
    ids = {client.get("/health").headers["x-request-id"] for _ in range(5)}
    assert len(ids) == 5


def test_valid_incoming_request_id_is_propagated(client):
    response = client.get("/health", headers={"X-Request-ID": "frontend-req-0001"})
    assert response.headers["x-request-id"] == "frontend-req-0001"


def test_malformed_incoming_request_id_is_replaced(client):
    response = client.get("/health", headers={"X-Request-ID": "bad id <script>"})
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


def test_error_body_and_header_carry_same_request_id(client):
    response = client.get("/missing", headers={"X-Request-ID": "trace-me-123456"})
    assert response.json()["error"]["request_id"] == "trace-me-123456"
    assert response.headers["x-request-id"] == "trace-me-123456"


def test_access_log_line_includes_request_id_and_no_query_string(client, caplog):
    caplog.set_level(logging.INFO, logger="sakshampay.access")
    client.get("/health?token=should-not-be-logged", headers={"X-Request-ID": "log-check-0001"})
    record = next(r for r in caplog.records if r.name == "sakshampay.access")
    assert record.request_id == "log-check-0001"
    assert record.path == "/health"
    assert record.status_code == 200
    # Only the application's own log records matter (the test HTTP client logs URLs itself)
    app_records = [r for r in caplog.records if r.name.startswith("sakshampay")]
    assert all("should-not-be-logged" not in str(vars(r)) for r in app_records)
