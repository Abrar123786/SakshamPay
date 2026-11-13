"""Regression: API timestamps are UTC ("Z") whatever the database session time zone.

Found on a developer machine whose PostgreSQL server ``TimeZone`` is Asia/Kolkata:
psycopg returns ``TIMESTAMP WITH TIME ZONE`` values in the session time zone, so a
value read back from the database (idempotent replay, repeated action, GET) was
written as ``+05:30`` while the same value set in Python a moment earlier was written
as ``Z``. Here the schema's engine forces the session time zone to Asia/Kolkata, so
these tests reproduce that machine on any server.

Each test compares the original response with the re-read one field by field
(identical strings), checks the ``Z`` form, and checks the exact stored instant,
microseconds included.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.session import Database
from app.models import Transaction
from tests.conftest import make_settings
from tests.payments_support import PASSWORD, Actor, db_assessments, db_transaction, make_app, set_deadline
from tests.pg import require_postgres_url, throwaway_schema

PG_URL = require_postgres_url()
SESSION_ZONE = "Asia/Kolkata"
TRANSACTION_TIMES = ("initiated_at", "expires_at", "completed_at", "server_time")
STORED_TIMES = ("initiated_at", "expires_at", "completed_at")


@pytest.fixture(scope="module")
def engine():
    with throwaway_schema(PG_URL, timezone=SESSION_ZONE) as engine:
        yield engine


@pytest.fixture
def app(engine):
    return make_app(engine, PG_URL)


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def actor(engine, client):
    return Actor(engine, client)


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def assert_utc_z(value: str | None) -> None:
    if value is None:
        return
    assert value.endswith("Z"), value
    assert parse(value).utcoffset().total_seconds() == 0


def times(body: dict) -> dict:
    """Every timestamp in a transaction response except server_time (which is 'now')."""
    found = {name: body[name] for name in TRANSACTION_TIMES if name != "server_time"}
    found["assessed_at"] = body["assessment"]["assessed_at"] if body["assessment"] else None
    return found


def assert_matches_database(engine, body: dict) -> None:
    """Each serialised value is exactly the stored instant, microseconds included."""
    stored = db_transaction(engine, body["id"])
    for name in STORED_TIMES:
        value = getattr(stored, name)
        if value is None:
            assert body[name] is None
            continue
        assert value.utcoffset().total_seconds() == 19800  # the test really read +05:30 values
        assert parse(body[name]) == value
        assert body[name] == value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    (assessment,) = db_assessments(engine, body["id"])
    assert parse(body["assessment"]["assessed_at"]) == assessment.assessed_at


def test_the_session_really_uses_a_non_utc_zone(engine):
    with engine.connect() as connection:
        assert connection.execute(text("SHOW timezone")).scalar() == SESSION_ZONE
        assert connection.execute(text("SELECT clock_timestamp()")).scalar().utcoffset().total_seconds() == 19800


def test_create_and_idempotent_replay_serialise_identically(engine, actor):
    beneficiary = actor.beneficiary_id()
    first = actor.pay(beneficiary, key="tz-replay-000001")
    replay = actor.pay(beneficiary, key="tz-replay-000001")
    assert (first.status_code, replay.status_code) == (201, 200)
    assert times(first.json()) == times(replay.json())
    for body in (first.json(), replay.json()):
        for value in [*times(body).values(), body["server_time"]]:
            assert_utc_z(value)
        assert_matches_database(engine, body)


@pytest.mark.parametrize("action", [{"action": "CANCEL"}, {"action": "CONTINUE", "confirmed": True}])
def test_an_action_and_its_repeat_serialise_identically(engine, actor, action):
    transaction_id = actor.pay(actor.beneficiary_id()).json()["id"]
    first = actor.act(transaction_id, **action)
    repeat = actor.act(transaction_id, **action)
    read = actor.get(transaction_id)
    assert first.status_code == repeat.status_code == read.status_code == 200
    assert times(first.json()) == times(repeat.json()) == times(read.json())
    assert first.json()["completed_at"] is not None
    for body in (first.json(), repeat.json(), read.json()):
        for value in [*times(body).values(), body["server_time"]]:
            assert_utc_z(value)
        assert_matches_database(engine, body)


def test_verification_and_its_repeat_serialise_identically(engine, actor):
    transaction_id = actor.pay(actor.beneficiary_id(), 30_000_00, device=f"device-{uuid.uuid4().hex}").json()["id"]
    first = actor.act(transaction_id, "VERIFY", password=PASSWORD)
    repeat = actor.act(transaction_id, "VERIFY", password=PASSWORD)
    assert first.json()["approval_method"] == "VERIFIED"
    assert times(first.json()) == times(repeat.json())
    assert_matches_database(engine, repeat.json())


def test_lazy_expiry_and_a_later_read_serialise_identically(engine, actor):
    transaction_id = actor.pay(actor.beneficiary_id()).json()["id"]
    set_deadline(engine, transaction_id, seconds_from_now=-1)
    expired = actor.get(transaction_id)  # expires it: completed_at is set in Python here
    later = actor.get(transaction_id)  # and read back from the database here
    assert expired.json()["status"] == later.json()["status"] == "EXPIRED"
    assert times(expired.json()) == times(later.json())
    assert_utc_z(expired.json()["completed_at"])
    assert_matches_database(engine, later.json())


def test_microseconds_are_kept(engine, actor):
    body = actor.pay(actor.beneficiary_id()).json()
    with Session(engine) as session:  # a stored value with every microsecond digit significant
        session.execute(
            text("UPDATE transactions SET expires_at = :at WHERE id = :id"),
            {"at": datetime(2099, 1, 2, 3, 4, 5, 123456, tzinfo=UTC), "id": uuid.UUID(body["id"])},
        )
        session.commit()
    assert actor.get(body["id"]).json()["expires_at"] == "2099-01-02T03:04:05.123456Z"


def test_beneficiary_created_at_is_the_same_when_listed(engine, actor):
    created = actor.add_beneficiary("Zone Check").json()
    (listed,) = [item for item in actor.client.get("/api/v1/beneficiaries", headers=actor.headers()).json()["items"]
                 if item["id"] == created["id"]]
    assert created["created_at"] == listed["created_at"]
    assert_utc_z(listed["created_at"])


def test_auth_and_dashboard_timestamps_are_utc(engine, client, actor):
    me = client.get("/api/v1/auth/me", headers=actor.headers(device=None)).json()
    assert_utc_z(me["created_at"])
    with Session(engine) as session:
        stored = session.scalar(text("SELECT created_at FROM users WHERE id = :id"), {"id": actor.id})
    assert parse(me["created_at"]) == stored
    login = client.post("/api/v1/auth/login", json={"email": actor.user.email, "password": PASSWORD}).json()
    assert_utc_z(login["expires_at"])
    period = client.get("/api/v1/dashboard/summary", headers=actor.headers(device=None)).json()["period"]
    assert_utc_z(period["start"])
    assert_utc_z(period["end"])


def test_the_application_connection_uses_utc_whatever_the_server_zone(engine):
    """The real engine (app.database.session.Database) sets timezone=UTC on every connection."""
    database = Database(make_settings(DATABASE_URL=PG_URL))
    try:
        with database.create_session() as session:
            assert session.execute(text("SHOW timezone")).scalar() == "UTC"
            assert session.execute(text("SELECT clock_timestamp()")).scalar().utcoffset().total_seconds() == 0
            assert session.execute(text("SHOW statement_timeout")).scalar() == "3s"  # the other option still applies
    finally:
        database.dispose()


def test_instants_are_unchanged_by_the_session_zone(engine, actor):
    """The same row read through a UTC session and an Asia/Kolkata session is the same instant."""
    body = actor.pay(actor.beneficiary_id()).json()
    database = Database(make_settings(DATABASE_URL=PG_URL))
    try:
        with Session(engine) as kolkata, database.create_session() as utc:
            schema = kolkata.execute(text("SELECT current_schema()")).scalar()
            utc.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            local_value = kolkata.get(Transaction, uuid.UUID(body["id"])).initiated_at
            utc_value = utc.get(Transaction, uuid.UUID(body["id"])).initiated_at
        assert local_value == utc_value
        assert (local_value.utcoffset().total_seconds(), utc_value.utcoffset().total_seconds()) == (19800, 0)
    finally:
        database.dispose()
