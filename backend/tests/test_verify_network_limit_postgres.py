"""P-10 review: the per-network (IP prefix) Verify limit, against PostgreSQL.

P-1: Verify attempts are rate-limited per account and per IP prefix. The per-account
limit is always on (test_transactions_actions_postgres.py). The per-network limit
counts VERIFICATION_FAILED audit rows from every account on one /24 (IPv6 /48) in
15 minutes. It is off by default (VERIFY_PREFIX_LIMIT_ENABLED). These tests turn it
on with a small limit to keep them fast; the default number (20) is checked too.
"""

import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import TransactionStatus
from app.repositories.locks import VERIFY_PREFIX
from tests.payments_support import PASSWORD, Actor, audit_actions, db_transaction, make_app, run_together, set_deadline
from tests.pg import require_postgres_url, throwaway_schema

PG_URL = require_postgres_url()
S = TransactionStatus
WRONG = "not-the-password"
LIMIT = 4


@pytest.fixture(scope="module")
def engine():
    with throwaway_schema(PG_URL) as engine:
        yield engine


@pytest.fixture
def app(engine):
    return make_app(engine, PG_URL, VERIFY_PREFIX_LIMIT_ENABLED=True, VERIFY_PREFIX_FAILURE_LIMIT=LIMIT)


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def at(app, host):
    """A client whose requests come from ``host``."""
    return TestClient(app, client=(host, 50000), raise_server_exceptions=False)


def unique_net():
    """A fresh /24 for each test (module-scoped data would otherwise leak between tests)."""
    value = uuid.uuid4().int
    return f"10.{value % 250}.{(value >> 8) % 250}"


def high(actor):
    body = actor.pay(actor.beneficiary_id(f"Payee {uuid.uuid4().hex[:6]}"), 30_000_00, device=f"device-{uuid.uuid4().hex}").json()
    assert body["assessment"]["risk_level"] == "HIGH"
    return body["id"]


def error(response):
    return response.status_code, response.json()["error"]["code"]


def fail_once_from(engine, client, app, host):
    """A new account fails one verification from ``host``."""
    actor = Actor(engine, client)
    assert error(actor.act(high(actor), "VERIFY", password=WRONG, client=at(app, host))) == (403, "VERIFICATION_FAILED")
    return actor


def network_failures(engine, network):
    with Session(engine) as session:
        return session.scalar(
            text("SELECT count(*) FROM audit_logs WHERE action = 'VERIFICATION_FAILED' AND ip_address = CAST(:n AS inet)"),
            {"n": network},
        )


def test_the_limit_is_off_by_default_and_20_when_on():
    fields = Settings.model_fields
    assert (fields["VERIFY_PREFIX_LIMIT_ENABLED"].default, fields["VERIFY_PREFIX_FAILURE_LIMIT"].default) == (False, 20)


def test_failures_from_different_accounts_on_one_network_are_limited(app, engine, client):
    net = unique_net()
    for n in range(LIMIT):
        fail_once_from(engine, client, app, f"{net}.{10 + n}")
    assert network_failures(engine, f"{net}.0/24") == LIMIT

    newcomer = Actor(engine, client)
    transaction_id = high(newcomer)
    for password in (PASSWORD, WRONG):  # even the right password: no guess is checked
        assert error(newcomer.act(transaction_id, "VERIFY", password=password, client=at(app, f"{net}.200"))) == (
            429, "TOO_MANY_VERIFICATION_ATTEMPTS")
    stored = db_transaction(engine, transaction_id)
    assert (stored.status, stored.verify_attempts) == (S.AWAITING_USER_ACTION, 0)
    assert "VERIFICATION_FAILED" not in audit_actions(engine, transaction_id)
    assert network_failures(engine, f"{net}.0/24") == LIMIT  # nothing recorded past the limit
    assert newcomer.act(transaction_id, "CANCEL").json()["status"] == "CANCELLED"  # cancelling is still possible


def test_other_networks_are_not_affected(app, engine, client):
    net = unique_net()
    for n in range(LIMIT):
        fail_once_from(engine, client, app, f"{net}.{n + 1}")
    elsewhere = Actor(engine, client)
    assert elsewhere.act(high(elsewhere), "VERIFY", password=PASSWORD, client=at(app, "198.51.100.7")).json()["status"] == "APPROVED"


def test_ipv4_mapped_addresses_count_as_their_ipv4_network(app, engine, client):
    net = unique_net()
    for n in range(LIMIT - 1):
        fail_once_from(engine, client, app, f"{net}.{n + 1}")
    fail_once_from(engine, client, app, f"::ffff:{net}.99")  # the same network, written as IPv6
    assert network_failures(engine, f"{net}.0/24") == LIMIT
    late = Actor(engine, client)
    assert error(late.act(high(late), "VERIFY", password=PASSWORD, client=at(app, f"{net}.5"))) == (429, "TOO_MANY_VERIFICATION_ATTEMPTS")


def test_ipv6_is_grouped_by_48(app, engine, client):
    block = f"2001:db8:{uuid.uuid4().int % 65000:x}"
    for n in range(LIMIT):
        fail_once_from(engine, client, app, f"{block}:{n + 1}::1")
    same, other = Actor(engine, client), Actor(engine, client)
    assert error(same.act(high(same), "VERIFY", password=PASSWORD, client=at(app, f"{block}:ffff::9"))) == (
        429, "TOO_MANY_VERIFICATION_ATTEMPTS")
    assert other.act(high(other), "VERIFY", password=PASSWORD, client=at(app, "2001:db9::1")).json()["status"] == "APPROVED"


def test_the_window_is_fifteen_minutes(app, engine, client, monkeypatch):
    from app.services.transactions import TransactionService

    net = unique_net()
    for n in range(LIMIT):
        fail_once_from(engine, client, app, f"{net}.{n + 1}")
    later = Actor(engine, client)
    transaction_id = high(later)
    set_deadline(engine, transaction_id, seconds_from_now=3600)  # keep it open while time moves on
    monkeypatch.setattr(TransactionService, "_now", staticmethod(lambda: datetime.now(UTC) + timedelta(minutes=16)))
    assert later.act(transaction_id, "VERIFY", password=PASSWORD, client=at(app, f"{net}.50")).json()["status"] == "APPROVED"


def test_requests_without_a_known_address_are_never_pooled(engine, client):
    # The default test client reports the host "testclient", which is not an address.
    for _ in range(LIMIT + 2):
        actor = Actor(engine, client)
        assert error(actor.act(high(actor), "VERIFY", password=WRONG)) == (403, "VERIFICATION_FAILED")
    last = Actor(engine, client)
    assert last.act(high(last), "VERIFY", password=PASSWORD).json()["status"] == "APPROVED"


def test_when_disabled_only_the_account_limit_applies(engine):
    app = make_app(engine, PG_URL, VERIFY_PREFIX_FAILURE_LIMIT=1)  # enabled flag left at its default (off)
    with TestClient(app, raise_server_exceptions=False) as client:
        net = unique_net()
        for n in range(3):
            fail_once_from(engine, client, app, f"{net}.{n + 1}")
        actor = Actor(engine, client)
        assert actor.act(high(actor), "VERIFY", password=PASSWORD, client=at(app, f"{net}.9")).json()["status"] == "APPROVED"


def test_the_account_limit_still_applies_across_networks(app, engine, client):
    actor = Actor(engine, client)
    first, second, third = high(actor), high(actor), high(actor)
    hosts = iter(f"{unique_net()}.1" for _ in range(5))  # five different networks
    for _ in range(3):
        actor.act(first, "VERIFY", password=WRONG, client=at(app, next(hosts)))
    for _ in range(2):
        actor.act(second, "VERIFY", password=WRONG, client=at(app, next(hosts)))
    assert error(actor.act(third, "VERIFY", password=PASSWORD, client=at(app, "198.51.100.77"))) == (
        429, "TOO_MANY_VERIFICATION_ATTEMPTS")


@pytest.mark.parametrize("round_number", range(3))
def test_concurrent_failures_from_one_network_are_counted_exactly(app, engine, client, round_number):
    net = unique_net()
    for n in range(LIMIT - 1):
        fail_once_from(engine, client, app, f"{net}.{n + 1}")
    racers = [Actor(engine, client) for _ in range(6)]
    payments = [high(racer) for racer in racers]
    clients = [at(app, f"{net}.{100 + n}") for n in range(6)]
    responses = run_together([lambda r=r, p=p, c=c: r.act(p, "VERIFY", password=WRONG, client=c)
                              for r, p, c in zip(racers, payments, clients, strict=True)])
    assert all(not isinstance(r, Exception) for r in responses), responses
    assert sorted(error(r) for r in responses) == [(403, "VERIFICATION_FAILED")] + [(429, "TOO_MANY_VERIFICATION_ATTEMPTS")] * 5
    assert network_failures(engine, f"{net}.0/24") == LIMIT


@pytest.mark.parametrize("round_number", range(3))
def test_a_correct_password_racing_wrong_ones_never_exceeds_the_limit(app, engine, client, round_number):
    net = unique_net()
    for n in range(LIMIT - 1):
        fail_once_from(engine, client, app, f"{net}.{n + 1}")
    racers = [Actor(engine, client) for _ in range(5)]
    payments = [high(racer) for racer in racers]
    passwords = [PASSWORD] + [WRONG] * 4
    responses = run_together([lambda r=r, p=p, w=w, n=n: r.act(p, "VERIFY", password=w, client=at(app, f"{net}.{150 + n}"))
                              for n, (r, p, w) in enumerate(zip(racers, payments, passwords, strict=True))])
    assert all(not isinstance(r, Exception) for r in responses), responses
    approved = [r for r in responses if r.status_code == 200]
    assert len(approved) <= 1
    assert network_failures(engine, f"{net}.0/24") == LIMIT  # exactly one more failure was recorded
    assert sum(db_transaction(engine, p).status == S.APPROVED for p in payments) == len(approved)


def test_a_held_network_lock_means_busy_and_nothing_changes(app, engine, client):
    net = unique_net()
    actor = Actor(engine, client)
    transaction_id = high(actor)
    holder = Session(engine)
    holder.execute(text("SELECT pg_advisory_xact_lock(:ns, hashtext(:key))"), {"ns": VERIFY_PREFIX, "key": f"{net}.0/24"})
    try:
        started = time.monotonic()
        responses = [actor.act(transaction_id, "VERIFY", password=p, client=at(app, f"{net}.3")) for p in (WRONG, PASSWORD)]
        waited = time.monotonic() - started
    finally:
        holder.rollback()
        holder.close()
    assert [error(r) for r in responses] == [(503, "SERVICE_BUSY")] * 2
    assert waited < 7
    stored = db_transaction(engine, transaction_id)
    assert (stored.status, stored.verify_attempts) == (S.AWAITING_USER_ACTION, 0)
    assert "VERIFICATION_FAILED" not in audit_actions(engine, transaction_id)
    assert actor.act(transaction_id, "VERIFY", password=PASSWORD, client=at(app, f"{net}.3")).json()["status"] == "APPROVED"


def test_addresses_are_never_stored_returned_or_logged(app, engine, client, caplog):
    net = unique_net()
    raw_hosts = [f"{net}.{n + 11}" for n in range(LIMIT)]
    with caplog.at_level("DEBUG"):
        for host in raw_hosts:
            fail_once_from(engine, client, app, host)
        blocked = Actor(engine, client)
        response = blocked.act(high(blocked), "VERIFY", password=PASSWORD, client=at(app, f"{net}.99"))
    assert error(response) == (429, "TOO_MANY_VERIFICATION_ATTEMPTS")
    assert net not in response.text and "context" not in response.json()["error"]  # neither the network nor which limit
    with Session(engine) as session:
        stored = session.scalars(text("SELECT host(ip_address) || '/' || masklen(ip_address) FROM audit_logs WHERE ip_address <<= CAST(:n AS inet)"),
                                 {"n": f"{net}.0/24"}).all()
    assert stored and set(stored) == {f"{net}.0/24"}
    logged = json.dumps([str(record.__dict__) for record in caplog.records])
    assert not any(host in logged for host in [*raw_hosts, f"{net}.99"])
