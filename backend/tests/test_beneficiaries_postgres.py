"""P-10c: GET and POST /api/v1/beneficiaries against PostgreSQL."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.payments_support import BENEFICIARIES, Actor, make_app
from tests.pg import require_postgres_url, throwaway_schema

PG_URL = require_postgres_url()
RAW_UPI = "ravi.kumar@okbank"
RAW_ACCOUNT = "5010 0123-4567 89"


@pytest.fixture(scope="module")
def engine():
    with throwaway_schema(PG_URL) as engine:
        yield engine


@pytest.fixture
def client(engine):
    with TestClient(make_app(engine, PG_URL), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def actor(engine, client):
    return Actor(engine, client)


def stored_rows(engine, user_id):
    with Session(engine) as session:
        return [dict(row._mapping) for row in session.execute(text("SELECT * FROM beneficiaries WHERE user_id = :u ORDER BY created_at"), {"u": user_id})]


def test_requires_authentication(client):
    assert client.get(BENEFICIARIES).status_code == 401
    assert client.post(BENEFICIARIES, json={"beneficiary_name": "X", "upi_id": RAW_UPI}).status_code == 401


def test_add_with_upi_id_stores_only_mask_and_fingerprint(engine, actor):
    response = actor.add_beneficiary("  Ravi Kumar ", upi_id="Ravi.Kumar@OKBANK")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "beneficiary_name", "bank_name", "upi_id_masked", "account_reference_masked", "is_verified", "created_at"}
    assert (body["beneficiary_name"], body["upi_id_masked"], body["account_reference_masked"], body["is_verified"]) == ("Ravi Kumar", "ra****@okbank", None, False)
    assert RAW_UPI not in response.text.lower()

    (row,) = stored_rows(engine, actor.id)
    assert row["upi_id_masked"] == "ra****@okbank" and len(row["upi_id_fingerprint"]) == 64
    assert RAW_UPI not in " ".join(str(value).lower() for value in row.values())  # the raw ID is nowhere in the row


def test_add_with_account_reference(engine, actor):
    response = actor.add_beneficiary("Meera Nair", account_reference=RAW_ACCOUNT, bank_name="Example Bank")
    assert response.status_code == 201
    body = response.json()
    assert (body["account_reference_masked"], body["bank_name"], body["upi_id_masked"]) == ("XXXXXXXXXX6789", "Example Bank", None)
    (row,) = stored_rows(engine, actor.id)
    assert "50100123456789" not in " ".join(str(value) for value in row.values())


def test_audit_records_the_event_without_the_identifier(engine, actor):
    beneficiary_id = actor.add_beneficiary(upi_id=RAW_UPI).json()["id"]
    with Session(engine) as session:
        rows = session.execute(text("SELECT action, actor_type, entity_type, entity_id::text, metadata::text FROM audit_logs WHERE user_id = :u"), {"u": actor.id}).all()
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [("BENEFICIARY_ADDED", "USER", "beneficiary", beneficiary_id)]
    assert rows[0][4] == '{"identifier_type": "upi"}'


def test_list_is_newest_first_and_only_your_own(engine, client, actor):
    other = Actor(engine, client)
    other.add_beneficiary("Not Yours")
    actor.add_beneficiary("First")
    actor.add_beneficiary("Second")
    response = client.get(BENEFICIARIES, headers=actor.headers(device=None))
    assert response.status_code == 200
    assert [item["beneficiary_name"] for item in response.json()["items"]] == ["Second", "First"]


def test_inactive_payees_are_not_listed(engine, client, actor):
    actor.add_beneficiary("Gone")
    with Session(engine) as session:
        session.execute(text("UPDATE beneficiaries SET is_active = false WHERE user_id = :u"), {"u": actor.id})
        session.commit()
    assert client.get(BENEFICIARIES, headers=actor.headers(device=None)).json() == {"items": []}


def test_duplicate_identifier_is_rejected_for_the_same_user_only(engine, client, actor):
    assert actor.add_beneficiary(upi_id=RAW_UPI).status_code == 201
    duplicate = actor.add_beneficiary("Another Name", upi_id=" RAVI.kumar@okbank ")
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "BENEFICIARY_ALREADY_EXISTS"
    assert Actor(engine, client).add_beneficiary(upi_id=RAW_UPI).status_code == 201  # payees are per user
    assert len(stored_rows(engine, actor.id)) == 1


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"beneficiary_name": "X"}, "VALIDATION_ERROR"),  # no identifier
        ({"beneficiary_name": "X", "upi_id": RAW_UPI, "account_reference": "501001234567"}, "VALIDATION_ERROR"),  # both
        ({"beneficiary_name": "X", "upi_id": RAW_UPI, "bank_name": "Bank"}, "VALIDATION_ERROR"),
        ({"beneficiary_name": "   ", "upi_id": RAW_UPI}, "VALIDATION_ERROR"),
        ({"beneficiary_name": "X" * 101, "upi_id": RAW_UPI}, "VALIDATION_ERROR"),
        ({"beneficiary_name": "X", "upi_id": RAW_UPI, "user_id": "9f1c2a5e-0000-4000-8000-000000000001"}, "VALIDATION_ERROR"),
        ({"beneficiary_name": "X", "upi_id": RAW_UPI, "is_verified": True}, "VALIDATION_ERROR"),
        ({"beneficiary_name": "X", "upi_id": "not-a-upi-id"}, "INVALID_IDENTIFIER"),
        ({"beneficiary_name": "X", "account_reference": "12-34"}, "INVALID_IDENTIFIER"),
    ],
)
def test_invalid_requests_store_nothing(engine, client, actor, body, code):
    response = client.post(BENEFICIARIES, json=body, headers=actor.headers(device=None))
    assert response.status_code == 422 and response.json()["error"]["code"] == code
    assert stored_rows(engine, actor.id) == []


def test_validation_errors_do_not_echo_the_identifier(client, actor):
    response = client.post(BENEFICIARIES, json={"beneficiary_name": "", "upi_id": RAW_UPI}, headers=actor.headers(device=None))
    assert response.status_code == 422 and RAW_UPI not in response.text


def test_without_the_hash_key_nothing_is_stored(engine):
    app = make_app(engine, PG_URL)
    app.state.settings = app.state.settings.model_copy(update={"IDENTIFIER_HASH_KEY": None})
    with TestClient(app, raise_server_exceptions=False) as client:
        actor = Actor(engine, client)
        response = actor.add_beneficiary(upi_id=RAW_UPI)
    assert response.status_code == 500 and response.json()["error"]["code"] == "CONFIGURATION_ERROR"
    assert stored_rows(engine, actor.id) == []
