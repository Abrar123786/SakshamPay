"""P-10 review: the per-user creation lock (R3 velocity under concurrency) and the
corrected R5/R6 history rules, through the real endpoints against PostgreSQL.

Velocity must count concurrent attempts consistently: the n-th attempt of a user
counts the n-1 before it, whatever order their assessments finish in. Other users
never wait for the lock, idempotency still holds, and nothing deadlocks.
"""

import json
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import TransactionStatus
from app.repositories import AuditLogRepository, BeneficiaryRepository
from app.repositories.locks import CREATE_PAYMENT
from tests.payments_support import (
    DEVICE,
    PASSWORD,
    Actor,
    add_payment,
    audit_actions,
    count_transactions,
    db_assessments,
    db_transaction,
    make_app,
    new_client,
    night_points,
    run_together,
)
from tests.pg import require_postgres_url, throwaway_schema

PG_URL = require_postgres_url()
S = TransactionStatus
LIFECYCLE = ["TRANSACTION_INITIATED", "TRANSACTION_ASSESSED", "TRANSACTION_AWAITING_ACTION", "ML_UNAVAILABLE"]


@pytest.fixture(scope="module")
def engine():
    with throwaway_schema(PG_URL) as engine:
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


def velocity_counts(engine, transaction_ids):
    """(initiated_at, txn_count_10m, repeat flag, R3 fired) per payment, in initiated_at order."""
    rows = []
    for transaction_id in transaction_ids:
        (assessment,) = db_assessments(engine, transaction_id)
        snapshot = assessment.features_snapshot
        fired = any(entry.get("rule") == "R3" for entry in assessment.rule_details)
        rows.append((db_transaction(engine, transaction_id).initiated_at, snapshot["txn_count_10m"],
                     snapshot["repeat_same_payee_amount_5m"], fired))
    return sorted(rows)


def hold_creation_lock(engine, user_id):
    """An open database transaction holding the user's creation lock (the caller rolls it back)."""
    holder = Session(engine)
    holder.execute(text("SELECT pg_advisory_xact_lock(:ns, hashtext(:key))"), {"ns": CREATE_PAYMENT, "key": str(user_id)})
    return holder


# ---- R3: consistent velocity under concurrency ---------------------------------------------------------

def test_an_earlier_attempt_that_commits_late_is_still_counted(app, engine, actor, monkeypatch):
    """Deterministic version of the race: the first request is slow between taking its
    time and committing. Without the lock the second request would neither see it nor
    be seen by it (both would count 0)."""
    beneficiary = actor.beneficiary_id()
    original, slowed = AuditLogRepository.record, threading.Event()

    def slow_first_initiation(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if kwargs.get("action") == "TRANSACTION_INITIATED" and not slowed.is_set():
            slowed.set()
            time.sleep(0.6)  # after the insert, before the commit
        return result

    monkeypatch.setattr(AuditLogRepository, "record", slow_first_initiation)
    responses = {}

    def pay(name, amount):
        responses[name] = actor.pay(beneficiary, amount, client=new_client(app))

    first = threading.Thread(target=pay, args=("first", 100_00))
    first.start()
    assert slowed.wait(timeout=10)
    second = threading.Thread(target=pay, args=("second", 200_00))
    second.start()
    first.join(timeout=30)
    second.join(timeout=30)

    assert responses["first"].status_code == responses["second"].status_code == 201
    ids = [responses["first"].json()["id"], responses["second"].json()["id"]]
    counts = velocity_counts(engine, ids)
    assert [count for _, count, _, _ in counts] == [0, 1]
    assert counts[0][0] < counts[1][0]
    assert db_transaction(engine, ids[0]).initiated_at < db_transaction(engine, ids[1]).initiated_at


@pytest.mark.parametrize("round_number", range(8))
def test_a_concurrent_burst_counts_every_attempt_exactly(app, engine, client, round_number):
    burst = Actor(engine, client)
    beneficiary = burst.beneficiary_id()
    responses = run_together([lambda c=c, n=n: burst.pay(beneficiary, 100_00 + n, client=c)
                              for n, c in enumerate(new_client(app) for _ in range(5))])
    assert all(not isinstance(r, Exception) and r.status_code == 201 for r in responses), responses
    ids = [r.json()["id"] for r in responses]
    counts = velocity_counts(engine, ids)
    assert [count for _, count, _, _ in counts] == [0, 1, 2, 3, 4]
    assert [fired for _, _, _, fired in counts] == [False, False, True, True, True]  # from the 3rd attempt
    times = [at for at, _, _, _ in counts]
    assert len(set(times)) == 5  # strictly increasing database-clock times
    for transaction_id in ids:  # the lifecycle is unchanged
        assert db_transaction(engine, transaction_id).status == S.AWAITING_USER_ACTION
        assert audit_actions(engine, transaction_id) == LIFECYCLE


def test_two_tabs_paying_the_same_payee_and_amount_flag_exactly_one_repeat(app, engine, actor):
    beneficiary = actor.beneficiary_id()
    responses = run_together([lambda c=c: actor.pay(beneficiary, 750_00, client=c) for c in (new_client(app), new_client(app))])
    ids = [r.json()["id"] for r in responses]
    assert len(set(ids)) == 2  # different keys: two payments (P-1), the later one flagged
    assert [repeat for _, _, repeat, _ in velocity_counts(engine, ids)] == [False, True]


def test_same_key_and_different_keys_together(app, engine, actor):
    beneficiary = actor.beneficiary_id()
    calls = [lambda c=c: actor.pay(beneficiary, 900_00, key="tab-one-0001", client=c) for c in [new_client(app) for _ in range(4)]]
    calls += [lambda c=c, n=n: actor.pay(beneficiary, 901_00 + n, client=c) for n, c in enumerate(new_client(app) for _ in range(3))]
    responses = run_together(calls)
    assert all(not isinstance(r, Exception) for r in responses), responses
    assert sorted(r.status_code for r in responses[:4]) == [200, 200, 200, 201]
    assert len({r.json()["id"] for r in responses[:4]}) == 1
    assert count_transactions(engine, actor.id) == 4
    ids = {r.json()["id"] for r in responses}
    assert sorted(count for _, count, _, _ in velocity_counts(engine, ids)) == [0, 1, 2, 3]


def test_other_users_never_wait_for_the_lock(engine, client, actor):
    other = Actor(engine, client)
    beneficiary = other.beneficiary_id()
    holder = hold_creation_lock(engine, actor.id)
    try:
        started = time.monotonic()
        assert other.pay(beneficiary).status_code == 201
        assert time.monotonic() - started < 1.5
    finally:
        holder.rollback()
        holder.close()


def test_a_held_lock_means_busy_nothing_written_and_a_retry_succeeds(engine, actor):
    beneficiary = actor.beneficiary_id()
    holder = hold_creation_lock(engine, actor.id)
    try:
        started = time.monotonic()
        response = actor.pay(beneficiary, key="retry-after-busy-01")
        waited = time.monotonic() - started
    finally:
        holder.rollback()
        holder.close()
    assert response.status_code == 503 and response.json()["error"]["code"] == "SERVICE_BUSY"
    assert "Nothing was paid" in response.json()["error"]["message"]
    assert 1.5 < waited < 3.0  # the 2-second lock timeout, before the 3-second statement timeout
    assert count_transactions(engine, actor.id) == 0
    retry = actor.pay(beneficiary, key="retry-after-busy-01")
    assert retry.status_code == 201 and count_transactions(engine, actor.id) == 1


@pytest.mark.parametrize("round_number", range(3))
def test_creates_verify_and_cancel_for_one_user_do_not_deadlock(app, engine, actor, round_number):
    to_verify = actor.pay(actor.beneficiary_id("A"), 30_000_00, device=f"device-{uuid.uuid4().hex}").json()["id"]
    to_cancel = actor.pay(actor.beneficiary_id("B")).json()["id"]
    beneficiary = actor.beneficiary_id("C")
    calls = [lambda c=c, n=n: actor.pay(beneficiary, 100_00 + n, client=c) for n, c in enumerate(new_client(app) for _ in range(4))]
    calls.append(lambda c=new_client(app): actor.act(to_verify, "VERIFY", password=PASSWORD, client=c))
    calls.append(lambda c=new_client(app): actor.act(to_cancel, "CANCEL", client=c))
    responses = run_together(calls)
    assert all(not isinstance(r, Exception) for r in responses), responses
    assert [r.status_code for r in responses] == [201] * 4 + [200, 200]
    assert db_transaction(engine, to_verify).status == S.APPROVED
    assert db_transaction(engine, to_cancel).status == S.CANCELLED
    # A deadlock (40P01) or a lock wait past the timeout would have surfaced as a 503 above.


def test_the_lock_is_released_before_assessment(engine, actor, monkeypatch):
    """While one payment is being assessed, the same user can start another."""
    from app.services import transactions as service

    beneficiary = actor.beneficiary_id()
    original, inside = service.FeatureExtractor.build, threading.Event()

    def build_and_check(self, transaction, **kwargs):
        if not inside.is_set():
            inside.set()
            with Session(actor.engine) as probe:  # the creation lock must be free now
                assert probe.scalar(text("SELECT pg_try_advisory_xact_lock(:ns, hashtext(:key))"),
                                    {"ns": CREATE_PAYMENT, "key": str(actor.id)})
                probe.rollback()
        return original(self, transaction, **kwargs)

    monkeypatch.setattr(service.FeatureExtractor, "build", build_and_check)
    assert actor.pay(beneficiary).status_code == 201 and inside.is_set()


# ---- R5: only approved payments make a device known ------------------------------------------------------

def test_cancel_then_retry_still_flags_the_new_device(actor):
    beneficiary = actor.beneficiary_id()
    first = actor.pay(beneficiary, 100_00, device="new-phone-000001").json()
    assert "NEW_DEVICE" in [f["code"] for f in first["assessment"]["factors"]]
    assert actor.act(first["id"], "CANCEL").json()["status"] == "CANCELLED"
    retry = actor.pay(beneficiary, 4_999_00, device="new-phone-000001").json()  # different amount: no repeat flag
    assert "NEW_DEVICE" in [f["code"] for f in retry["assessment"]["factors"]]


def test_three_failed_verifications_do_not_make_a_device_known(actor):
    device = f"device-{uuid.uuid4().hex}"
    first = actor.pay(actor.beneficiary_id("A"), 30_000_00, device=device).json()
    for _ in range(3):
        actor.act(first["id"], "VERIFY", password="not-the-password")
    retry = actor.pay(actor.beneficiary_id("B"), 100_00, device=device).json()
    assert "NEW_DEVICE" in [f["code"] for f in retry["assessment"]["factors"]]


def test_an_approved_payment_makes_the_device_known(actor):
    beneficiary = actor.beneficiary_id()
    first = actor.pay(beneficiary, 100_00, device="laptop-00000001").json()
    assert actor.act(first["id"], "CONTINUE", confirmed=True).json()["status"] == "APPROVED"
    second = actor.pay(beneficiary, 7_300_00, device="laptop-00000001").json()
    assert "NEW_DEVICE" not in [f["code"] for f in second["assessment"]["factors"]]


# ---- R6: lifetime baseline for the dormant clause ---------------------------------------------------------

def test_a_user_back_after_120_days_gets_the_dormant_factor(engine, actor):
    """docs/payments.md example: 12 approved payments 300-120 days ago (lifetime p90 Rs 2,430),
    then Rs 20,000 to the same payee from the same browser."""
    beneficiary_id = uuid.UUID(actor.beneficiary_id("Old Payee"))
    now = datetime.now(UTC)
    amounts = [1_200_00] * 6 + [1_800_00] * 4 + [2_500_00, 3_000_00]
    with Session(engine, expire_on_commit=False) as session:
        beneficiary = BeneficiaryRepository(session).get_for_user(beneficiary_id, actor.id)
        beneficiary.created_at = now - timedelta(days=400)
        for i, amount in enumerate(amounts):
            add_payment(session, actor.user, beneficiary, amount, at=now - timedelta(days=120 + i * 15), device_id=DEVICE)
        session.commit()

    body = actor.pay(beneficiary_id, 20_000_00).json()
    assessment, night = body["assessment"], night_points(body)
    codes = [f["code"] for f in assessment["factors"]]
    assert assessment["rule_score"] == 15 + 15 + night  # R5 (device last approved 120 days ago) + R6 (+ R4 at night)
    assert "BEHAVIOUR_DEVIATION" in codes and "NEW_DEVICE" in codes and "LIMITED_HISTORY" in codes
    deviation = next(f for f in assessment["factors"] if f["code"] == "BEHAVIOUR_DEVIATION")
    assert deviation["label"] == "Large payment after a long gap"
    assert "2,430" not in json.dumps(body) and "percentile" not in json.dumps(body).lower()  # no baseline or trigger
    # 30 points by day is the top of LOW, raised to MEDIUM (rules only); 40 at night is MEDIUM.
    assert assessment["risk_level"] == "MEDIUM"
    assert assessment["level_raised_from"] == ("LOW" if night == 0 else None)
    (row,) = db_assessments(engine, body["id"])
    assert row.features_snapshot["lifetime_approved_count"] == 12
    assert row.features_snapshot["dormant_p90_paise"] == pytest.approx(2_430_00)
    assert row.features_snapshot["cold_start"] is True and row.features_snapshot["history_count"] == 0
