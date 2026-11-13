"""P-1: login attempts rate-limited per IP prefix, against PostgreSQL.

The per-account lockout (P-6) is always on. The per-network limit counts LOGIN_FAILED
audit rows from one /24 (IPv6 /48) in 15 minutes, for every account and for unknown
emails. It is off by default (LOGIN_PREFIX_LIMIT_ENABLED); these tests turn it on with
a small limit to stay fast. The default (off, 20) is checked too.
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
from app.models import User
from app.repositories.locks import LOGIN_PREFIX
from tests.payments_support import PASSWORD, Actor, make_app, run_together
from tests.pg import require_postgres_url, throwaway_schema

PG_URL = require_postgres_url()
pytestmark = pytest.mark.usefixtures("fast_password_hashing")
LOGIN = "/api/v1/auth/login"
LIMIT = 4
WRONG = "not-the-password"


@pytest.fixture(scope="module")
def engine():
    with throwaway_schema(PG_URL) as engine:
        yield engine


@pytest.fixture
def app(engine):
    return make_app(engine, PG_URL, LOGIN_PREFIX_LIMIT_ENABLED=True, LOGIN_PREFIX_FAILURE_LIMIT=LIMIT)


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def at(app, host):
    return TestClient(app, client=(host, 50000), raise_server_exceptions=False)


def unique_net():
    value = uuid.uuid4().int
    return f"10.{value % 250}.{(value >> 8) % 250}"


def login(client, email, password):
    return client.post(LOGIN, json={"email": email, "password": password})


def error(response):
    return response.status_code, response.json()["error"]["code"]


def account(engine, client):
    return Actor(engine, client).user


def failures_from(engine, network):
    with Session(engine) as session:
        return session.scalar(
            text("SELECT count(*) FROM audit_logs WHERE action = 'LOGIN_FAILED' AND ip_address = CAST(:n AS inet)"), {"n": network}
        )


def audit_rows_for(engine, user_id):
    with Session(engine) as session:
        return session.scalar(text("SELECT count(*) FROM audit_logs WHERE user_id = :u"), {"u": user_id})


def stored(engine, user_id):
    with Session(engine, expire_on_commit=False) as session:
        return session.get(User, user_id)


def fill(engine, client, app, net, count):
    """``count`` failed logins from ``net``: wrong passwords for real accounts and unknown emails."""
    for n in range(count):
        email = account(engine, client).email if n % 2 else f"nobody.{uuid.uuid4().hex[:8]}@example.com"
        assert error(login(at(app, f"{net}.{n + 1}"), email, WRONG)) == (401, "INVALID_CREDENTIALS")


def test_the_limit_is_off_by_default_and_20_when_on():
    fields = Settings.model_fields
    assert (fields["LOGIN_PREFIX_LIMIT_ENABLED"].default, fields["LOGIN_PREFIX_FAILURE_LIMIT"].default) == (False, 20)


def test_failures_from_many_accounts_and_unknown_emails_block_the_network(app, engine, client):
    net = unique_net()
    fill(engine, client, app, net, LIMIT)
    assert failures_from(engine, f"{net}.0/24") == LIMIT

    user = account(engine, client)
    before, rows_before = stored(engine, user.id), audit_rows_for(engine, user.id)
    response = login(at(app, f"{net}.200"), user.email, PASSWORD)  # the right password
    assert error(response) == (429, "TOO_MANY_LOGIN_ATTEMPTS") and "access_token" not in response.text
    after = stored(engine, user.id)
    assert (after.failed_login_count, after.locked_until, after.last_login_at) == (
        before.failed_login_count, before.locked_until, before.last_login_at)
    assert audit_rows_for(engine, user.id) == rows_before  # nothing recorded
    assert failures_from(engine, f"{net}.0/24") == LIMIT


def test_the_block_does_not_reveal_whether_an_email_exists(app, engine, client):
    net = unique_net()
    fill(engine, client, app, net, LIMIT)
    known = login(at(app, f"{net}.9"), account(engine, client).email, WRONG)
    unknown = login(at(app, f"{net}.9"), f"ghost.{uuid.uuid4().hex[:8]}@example.com", WRONG)
    assert error(known) == error(unknown) == (429, "TOO_MANY_LOGIN_ATTEMPTS")
    assert known.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_other_networks_and_ipv6_grouping(app, engine, client):
    net = unique_net()
    fill(engine, client, app, net, LIMIT)
    user = account(engine, client)
    assert login(at(app, "198.51.100.23"), user.email, PASSWORD).status_code == 200
    assert error(login(at(app, f"::ffff:{net}.77"), user.email, PASSWORD)) == (429, "TOO_MANY_LOGIN_ATTEMPTS")  # IPv4-mapped

    block = f"2001:db8:{uuid.uuid4().int % 65000:x}"
    for n in range(LIMIT):
        login(at(app, f"{block}:{n + 1}::1"), f"v6.{uuid.uuid4().hex[:8]}@example.com", WRONG)
    assert error(login(at(app, f"{block}:ffff::2"), user.email, PASSWORD)) == (429, "TOO_MANY_LOGIN_ATTEMPTS")
    assert login(at(app, "2001:db9::5"), user.email, PASSWORD).status_code == 200


@pytest.mark.parametrize(("minutes_ago", "blocked"), [(14, True), (16, False)])
def test_the_window_is_fifteen_minutes(app, engine, client, minutes_ago, blocked):
    net = unique_net()
    with Session(engine) as session:  # earlier failures (append-only rows can be inserted with a past time)
        for _ in range(LIMIT):
            session.execute(
                text("INSERT INTO audit_logs (actor_type, action, metadata, ip_address, created_at) "
                     "VALUES ('ANONYMOUS', 'LOGIN_FAILED', '{\"reason\": \"unknown_account\"}', CAST(:n AS inet), :at)"),
                {"n": f"{net}.0/24", "at": datetime.now(UTC) - timedelta(minutes=minutes_ago)},
            )
        session.commit()
    response = login(at(app, f"{net}.5"), account(engine, client).email, PASSWORD)
    assert (response.status_code == 429) is blocked


def test_requests_without_a_known_address_are_never_pooled(engine, client):
    for _ in range(LIMIT + 2):  # the default test client's host "testclient" is not an address
        assert login(client, f"x.{uuid.uuid4().hex[:8]}@example.com", WRONG).status_code == 401
    assert login(client, account(engine, client).email, PASSWORD).status_code == 200


def test_when_disabled_only_the_account_lockout_applies(engine):
    app = make_app(engine, PG_URL, LOGIN_PREFIX_FAILURE_LIMIT=1)  # enabled flag left at its default (off)
    with TestClient(app, raise_server_exceptions=False) as client:
        net = unique_net()
        fill(engine, client, app, net, 3)
        assert login(at(app, f"{net}.9"), account(engine, client).email, PASSWORD).status_code == 200


def test_the_account_lockout_still_works_with_the_network_limit_on(app, engine, client):
    user = account(engine, client)
    for n in range(5):  # five different networks: the account limit, not the network one
        assert error(login(at(app, f"{unique_net()}.{n + 1}"), user.email, WRONG)) == (401, "INVALID_CREDENTIALS")
    assert stored(engine, user.id).locked_until is not None
    assert error(login(at(app, "198.51.100.200"), user.email, PASSWORD)) == (401, "INVALID_CREDENTIALS")  # locked


@pytest.mark.parametrize("round_number", range(3))
def test_concurrent_failures_from_one_network_are_counted_exactly(app, engine, client, round_number):
    net = unique_net()
    fill(engine, client, app, net, LIMIT - 1)
    users = [account(engine, client) for _ in range(6)]
    responses = run_together([lambda u=u, n=n: login(at(app, f"{net}.{100 + n}"), u.email, WRONG) for n, u in enumerate(users)])
    assert all(not isinstance(r, Exception) for r in responses), responses
    assert sorted(error(r) for r in responses) == [(401, "INVALID_CREDENTIALS")] + [(429, "TOO_MANY_LOGIN_ATTEMPTS")] * 5
    assert failures_from(engine, f"{net}.0/24") == LIMIT
    assert sum(stored(engine, u.id).failed_login_count for u in users) == 1  # only the recorded failure counted


@pytest.mark.parametrize("round_number", range(3))
def test_a_correct_password_racing_wrong_ones_never_exceeds_the_limit(app, engine, client, round_number):
    net = unique_net()
    fill(engine, client, app, net, LIMIT - 1)
    users = [account(engine, client) for _ in range(5)]
    passwords = [PASSWORD] + [WRONG] * 4
    responses = run_together([lambda u=u, p=p, n=n: login(at(app, f"{net}.{150 + n}"), u.email, p)
                              for n, (u, p) in enumerate(zip(users, passwords, strict=True))])
    assert all(not isinstance(r, Exception) for r in responses), responses
    assert sum(r.status_code == 200 for r in responses) <= 1
    assert failures_from(engine, f"{net}.0/24") == LIMIT


def test_logins_and_verifications_for_one_user_do_not_deadlock(app, engine, client):
    """Login takes the network lock, then the user row; Verify holds the user row and never
    waits for the login lock."""
    actor = Actor(engine, client)
    net = unique_net()
    transaction_id = actor.pay(actor.beneficiary_id(), 30_000_00, device=f"device-{uuid.uuid4().hex}").json()["id"]
    calls = [lambda n=n: login(at(app, f"{net}.{n + 1}"), actor.user.email, WRONG) for n in range(3)]
    calls.append(lambda: actor.act(transaction_id, "VERIFY", password=PASSWORD, client=at(app, f"{net}.50")))
    responses = run_together(calls)
    assert all(not isinstance(r, Exception) for r in responses), responses
    assert [r.status_code for r in responses] == [401, 401, 401, 200]


def test_a_held_network_lock_means_busy_and_nothing_is_written(app, engine, client):
    net = unique_net()
    user = account(engine, client)
    rows_before, last_login_before = audit_rows_for(engine, user.id), stored(engine, user.id).last_login_at
    holder = Session(engine)
    holder.execute(text("SELECT pg_advisory_xact_lock(:ns, hashtext(:key))"), {"ns": LOGIN_PREFIX, "key": f"{net}.0/24"})
    try:
        started = time.monotonic()
        response = login(at(app, f"{net}.3"), user.email, PASSWORD)
        waited = time.monotonic() - started
    finally:
        holder.rollback()
        holder.close()
    assert error(response) == (503, "SERVICE_BUSY") and waited < 3.5
    assert audit_rows_for(engine, user.id) == rows_before and stored(engine, user.id).last_login_at == last_login_before
    assert login(at(app, f"{net}.3"), user.email, PASSWORD).status_code == 200


def test_addresses_emails_and_passwords_never_appear_in_responses_or_logs(app, engine, client, caplog):
    net = unique_net()
    user = account(engine, client)
    with caplog.at_level("DEBUG"):
        fill(engine, client, app, net, LIMIT)
        response = login(at(app, f"{net}.99"), user.email, PASSWORD)
    assert error(response) == (429, "TOO_MANY_LOGIN_ATTEMPTS")
    assert net not in response.text and user.email not in response.text and "context" not in response.json()["error"]
    logged = json.dumps([str(record.__dict__) for record in caplog.records])
    assert net not in logged and user.email not in logged and PASSWORD not in logged and WRONG not in logged
