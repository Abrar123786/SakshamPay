"""P-10e: POST /api/v1/transactions/{id}/actions against PostgreSQL.

The state machine through the real endpoint: CANCEL, CONTINUE, VERIFY, their
guards per risk level, verification limits, expiry, ownership, concurrency, and
the rule that nothing is approved without an assessment and an explicit action.
"""

import json
import re
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import TransactionStatus
from tests.payments_support import (
    PASSWORD,
    Actor,
    alerts_for,
    audit_actions,
    audit_trail,
    db_transaction,
    make_app,
    new_client,
    run_together,
    set_deadline,
)
from tests.pg import require_postgres_url, throwaway_schema
from tests.test_transactions_create_postgres import FixedScorer

PG_URL = require_postgres_url()
S = TransactionStatus
WRONG = "not-the-password"


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


def medium(actor):
    body = actor.pay(actor.beneficiary_id(f"Payee {uuid.uuid4().hex[:6]}")).json()
    assert body["assessment"]["risk_level"] == "MEDIUM"
    return body["id"]


def high(actor):
    # A large payment to a new payee from a device not seen before: HIGH for a new account, every time.
    body = actor.pay(actor.beneficiary_id(f"Payee {uuid.uuid4().hex[:6]}"), 30_000_00, device=f"device-{uuid.uuid4().hex}").json()
    assert body["assessment"]["risk_level"] == "HIGH"
    return body["id"]


def error(response):
    return response.status_code, response.json()["error"]["code"]


# ---- CANCEL ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("make", [medium, high])
def test_cancel(engine, actor, make):
    transaction_id = make(actor)
    response = actor.act(transaction_id, "CANCEL")
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["approval_method"]) == ("CANCELLED", None) and body["completed_at"] is not None
    last = audit_trail(engine, transaction_id)[-1]
    assert (last.action, last.actor_type.value, last.old_values, last.new_values) == (
        "TRANSACTION_CANCELLED", "USER", {"status": "AWAITING_USER_ACTION"}, {"status": "CANCELLED", "reason": "user_cancelled"},
    )
    assert alerts_for(engine, transaction_id)[-1].alert_type.value == "TRANSACTION_CANCELLED"
    assert "Nothing was paid." in alerts_for(engine, transaction_id)[-1].message


def test_repeating_the_same_action_returns_the_same_state_once(engine, actor):
    transaction_id = medium(actor)
    first = actor.act(transaction_id, "CANCEL").json()
    again = actor.act(transaction_id, "CANCEL")
    assert again.status_code == 200 and again.json()["status"] == "CANCELLED"
    assert again.json()["completed_at"] == first["completed_at"]
    assert audit_actions(engine, transaction_id).count("TRANSACTION_CANCELLED") == 1
    assert [a.alert_type.value for a in alerts_for(engine, transaction_id)].count("TRANSACTION_CANCELLED") == 1


# ---- CONTINUE --------------------------------------------------------------------------------------------

def test_medium_continue_needs_explicit_confirmation(engine, actor):
    transaction_id = medium(actor)
    assert error(actor.act(transaction_id, "CONTINUE")) == (400, "CONFIRMATION_REQUIRED")
    assert error(actor.act(transaction_id, "CONTINUE", confirmed=False)) == (400, "CONFIRMATION_REQUIRED")
    assert db_transaction(engine, transaction_id).status == S.AWAITING_USER_ACTION

    response = actor.act(transaction_id, "CONTINUE", confirmed=True)
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["approval_method"]) == ("APPROVED", "CONTINUE") and body["completed_at"] is not None
    last = audit_trail(engine, transaction_id)[-1]
    assert (last.action, last.actor_type.value, last.new_values, last.event_metadata) == (
        "TRANSACTION_APPROVED", "USER", {"status": "APPROVED", "approval_method": "CONTINUE"}, {"simulated": True},
    )
    assert actor.act(transaction_id, "CONTINUE", confirmed=True).json()["status"] == "APPROVED"  # repeat: same state
    assert audit_actions(engine, transaction_id).count("TRANSACTION_APPROVED") == 1


def test_high_risk_cannot_be_continued(engine, actor):
    transaction_id = high(actor)
    for body in ({}, {"confirmed": True}):
        assert error(actor.act(transaction_id, "CONTINUE", **body)) == (403, "STEP_UP_REQUIRED")
    stored = db_transaction(engine, transaction_id)
    assert (stored.status, stored.approval_method) == (S.AWAITING_USER_ACTION, None)
    assert "TRANSACTION_APPROVED" not in audit_actions(engine, transaction_id)


def test_low_risk_continues_without_confirmation_and_has_no_verify(app, engine, actor):
    app.state.anomaly_scorer = FixedScorer(10)  # test double for a future model: makes LOW reachable
    body = actor.pay(actor.established(), 500_00).json()
    assert body["assessment"]["risk_level"] == "LOW"
    assert error(actor.act(body["id"], "VERIFY", password=PASSWORD)) == (409, "ACTION_NOT_ALLOWED")
    assert actor.act(body["id"], "CONTINUE").json()["approval_method"] == "CONTINUE"


# ---- VERIFY ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("make", [medium, high])
def test_verify_with_the_account_password_approves(engine, actor, make):
    transaction_id = make(actor)
    response = actor.act(transaction_id, "VERIFY", password=PASSWORD)
    assert response.status_code == 200
    assert (response.json()["status"], response.json()["approval_method"]) == ("APPROVED", "VERIFIED")
    assert audit_trail(engine, transaction_id)[-1].new_values == {"status": "APPROVED", "approval_method": "VERIFIED"}
    assert actor.act(transaction_id, "VERIFY", password="anything-at-all").json()["status"] == "APPROVED"  # repeat: state only
    assert audit_actions(engine, transaction_id).count("TRANSACTION_APPROVED") == 1


def test_three_wrong_passwords_cancel_the_payment(engine, actor):
    transaction_id = high(actor)
    for remaining, status in ((2, "AWAITING_USER_ACTION"), (1, "AWAITING_USER_ACTION"), (0, "CANCELLED")):
        response = actor.act(transaction_id, "VERIFY", password=WRONG)
        assert error(response) == (403, "VERIFICATION_FAILED")
        assert response.json()["error"]["context"] == {"attempts_remaining": remaining, "status": status}
        assert actor.get(transaction_id).json()["verify_attempts_remaining"] == remaining

    stored = db_transaction(engine, transaction_id)
    assert (stored.status, stored.verify_attempts, stored.approval_method) == (S.CANCELLED, 3, None)
    trail = audit_trail(engine, transaction_id)
    assert [e.action for e in trail][-4:] == ["VERIFICATION_FAILED", "VERIFICATION_FAILED", "VERIFICATION_FAILED", "TRANSACTION_CANCELLED"]
    assert trail[-2].event_metadata == {"attempt": 3, "attempts_remaining": 0}
    assert (trail[-1].actor_type.value, trail[-1].new_values) == ("SYSTEM", {"status": "CANCELLED", "reason": "verification_failed"})
    alert = alerts_for(engine, transaction_id)[-1]
    assert (alert.alert_type.value, alert.severity.value) == ("VERIFICATION_FAILED", "WARNING") and "Nothing was paid." in alert.message
    # The right password afterwards changes nothing.
    assert error(actor.act(transaction_id, "VERIFY", password=PASSWORD)) == (409, "INVALID_STATE_TRANSITION")


def test_a_wrong_password_then_the_right_one_approves(engine, actor):
    transaction_id = high(actor)
    assert error(actor.act(transaction_id, "VERIFY", password=WRONG)) == (403, "VERIFICATION_FAILED")
    assert actor.act(transaction_id, "VERIFY", password=PASSWORD).json()["approval_method"] == "VERIFIED"
    assert db_transaction(engine, transaction_id).verify_attempts == 1


def test_passwords_are_never_stored_logged_or_echoed(engine, actor, caplog):
    transaction_id = high(actor)
    secret = "s3cret-Guess-!@#"
    with caplog.at_level("DEBUG"):
        failed = actor.act(transaction_id, "VERIFY", password=secret)
        invalid = actor.act(transaction_id, "CANCEL", password=secret)  # 422: password with the wrong action
    assert invalid.status_code == 422
    assert secret not in failed.text and secret not in invalid.text and secret not in caplog.text
    stored = json.dumps([[e.old_values, e.new_values, e.event_metadata] for e in audit_trail(engine, transaction_id)])
    assert secret not in stored and "password" not in stored.lower()


def test_failed_verifications_are_limited_across_payments(engine, actor):
    first, second, third = high(actor), high(actor), high(actor)
    for _ in range(3):
        actor.act(first, "VERIFY", password=WRONG)  # cancelled on the third
    for _ in range(2):
        assert error(actor.act(second, "VERIFY", password=WRONG)) == (403, "VERIFICATION_FAILED")
    # Five failures in 15 minutes: no more guesses on any payment, even with the right password.
    for transaction_id in (second, third):
        assert error(actor.act(transaction_id, "VERIFY", password=PASSWORD)) == (429, "TOO_MANY_VERIFICATION_ATTEMPTS")
        assert error(actor.act(transaction_id, "VERIFY", password=WRONG)) == (429, "TOO_MANY_VERIFICATION_ATTEMPTS")
    assert (db_transaction(engine, second).status, db_transaction(engine, second).verify_attempts) == (S.AWAITING_USER_ACTION, 2)
    assert db_transaction(engine, third).verify_attempts == 0
    assert actor.act(third, "CANCEL").json()["status"] == "CANCELLED"  # cancelling is still possible


def test_the_limit_is_a_fifteen_minute_window(engine, actor, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from app.services.transactions import TransactionService

    first, second = high(actor), high(actor)
    for transaction_id, attempts in ((first, 3), (second, 2)):
        for _ in range(attempts):
            actor.act(transaction_id, "VERIFY", password=WRONG)
    assert error(actor.act(second, "VERIFY", password=PASSWORD)) == (429, "TOO_MANY_VERIFICATION_ATTEMPTS")

    set_deadline(engine, second, seconds_from_now=3600)  # keep the payment open while time moves on
    monkeypatch.setattr(TransactionService, "_now", staticmethod(lambda: datetime.now(UTC) + timedelta(minutes=16)))
    assert actor.act(second, "VERIFY", password=PASSWORD).json()["approval_method"] == "VERIFIED"


def test_the_limit_is_per_user(engine, client, actor):
    other = Actor(engine, client)
    for _ in range(2):
        transaction_id = high(actor)
        for _ in range(3):
            actor.act(transaction_id, "VERIFY", password=WRONG)
    assert other.act(high(other), "VERIFY", password=PASSWORD).json()["status"] == "APPROVED"


# ---- expiry, ownership, validation -----------------------------------------------------------------------

@pytest.mark.parametrize("action", [{"action": "CONTINUE", "confirmed": True}, {"action": "VERIFY", "password": PASSWORD}, {"action": "CANCEL"}])
def test_no_action_after_the_deadline(engine, actor, action):
    transaction_id = medium(actor)
    set_deadline(engine, transaction_id, seconds_from_now=-1)
    response = actor.act(transaction_id, **action)
    assert error(response) == (409, "TRANSACTION_EXPIRED")
    assert "Nothing was paid." in response.json()["error"]["message"]
    stored = db_transaction(engine, transaction_id)
    assert (stored.status, stored.approval_method) == (S.EXPIRED, None)
    assert audit_actions(engine, transaction_id)[-1] == "TRANSACTION_EXPIRED"
    assert error(actor.act(transaction_id, **action)) == (409, "TRANSACTION_EXPIRED")  # every later action too


@pytest.mark.parametrize("settle", ["read", "sweep"])
def test_an_action_on_a_payment_expired_by_a_read_or_the_sweep_gets_the_same_answer(engine, actor, settle):
    transaction_id = medium(actor)
    set_deadline(engine, transaction_id, seconds_from_now=-1)
    if settle == "read":
        assert actor.get(transaction_id).json()["status"] == "EXPIRED"
    else:
        actor.pay(actor.beneficiary_id("Sweep Trigger"))  # creating a payment sweeps overdue ones
        assert db_transaction(engine, transaction_id).status == S.EXPIRED
    for action in ({"action": "CONTINUE", "confirmed": True}, {"action": "CANCEL"}):
        assert error(actor.act(transaction_id, **action)) == (409, "TRANSACTION_EXPIRED")
    assert audit_actions(engine, transaction_id).count("TRANSACTION_EXPIRED") == 1


def test_actions_are_limited_to_the_owner(engine, client, actor):
    other = Actor(engine, client)
    transaction_id = medium(actor)
    for action in ({"action": "CANCEL"}, {"action": "CONTINUE", "confirmed": True}, {"action": "VERIFY", "password": PASSWORD}):
        assert error(other.act(transaction_id, **action)) == (404, "TRANSACTION_NOT_FOUND")
    assert error(actor.act(uuid.uuid4(), "CANCEL")) == (404, "TRANSACTION_NOT_FOUND")
    stored = db_transaction(engine, transaction_id)
    assert (stored.status, stored.verify_attempts) == (S.AWAITING_USER_ACTION, 0)
    assert client.post(f"/api/v1/transactions/{transaction_id}/actions", json={"action": "CANCEL"}).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"action": "APPROVE"},
        {"action": "VERIFY"},
        {"action": "VERIFY", "password": ""},
        {"action": "CONTINUE", "password": PASSWORD},
        {"action": "CANCEL", "confirmed": True},
        {"action": "CONTINUE", "confirmed": "yes"},
        {"action": "CONTINUE", "confirmed": True, "status": "APPROVED"},
        {"action": "CONTINUE", "confirmed": True, "approval_method": "VERIFIED"},
    ],
)
def test_invalid_action_requests_change_nothing(engine, client, actor, body):
    transaction_id = medium(actor)
    response = client.post(f"/api/v1/transactions/{transaction_id}/actions", json=body, headers=actor.headers(device=None))
    assert error(response) == (422, "VALIDATION_ERROR")
    assert db_transaction(engine, transaction_id).status == S.AWAITING_USER_ACTION


def test_a_finished_payment_cannot_be_changed(engine, actor):
    approved, cancelled = medium(actor), medium(actor)
    actor.act(approved, "CONTINUE", confirmed=True)
    actor.act(cancelled, "CANCEL")
    assert error(actor.act(approved, "CANCEL")) == (409, "INVALID_STATE_TRANSITION")
    assert error(actor.act(approved, "VERIFY", password=PASSWORD)) == (409, "INVALID_STATE_TRANSITION")  # approved by CONTINUE, not VERIFY
    assert error(actor.act(cancelled, "CONTINUE", confirmed=True)) == (409, "INVALID_STATE_TRANSITION")
    assert error(actor.act(cancelled, "VERIFY", password=PASSWORD)) == (409, "INVALID_STATE_TRANSITION")
    assert (db_transaction(engine, approved).status, db_transaction(engine, cancelled).status) == (S.APPROVED, S.CANCELLED)


# ---- concurrency -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("round_number", range(5))
def test_simultaneous_continue_and_cancel_have_exactly_one_winner(app, engine, actor, round_number):
    transaction_id = medium(actor)
    calls = []
    for _ in range(4):
        calls.append(lambda c=new_client(app): actor.act(transaction_id, "CONTINUE", confirmed=True, client=c))
        calls.append(lambda c=new_client(app): actor.act(transaction_id, "CANCEL", client=c))
    responses = run_together(calls)
    assert all(not isinstance(r, Exception) for r in responses), responses

    final = db_transaction(engine, transaction_id).status
    assert final in (S.APPROVED, S.CANCELLED)
    winners, losers = ("CONTINUE", "CANCEL") if final == S.APPROVED else ("CANCEL", "CONTINUE")
    for index, response in enumerate(responses):
        action = "CONTINUE" if index % 2 == 0 else "CANCEL"
        if action == winners:
            assert response.status_code == 200 and response.json()["status"] == final.value
        else:
            assert error(response) == (409, "INVALID_STATE_TRANSITION")
    actions = audit_actions(engine, transaction_id)
    assert actions.count("TRANSACTION_APPROVED") + actions.count("TRANSACTION_CANCELLED") == 1
    assert db_transaction(engine, transaction_id).version == 4  # INITIATED, ANALYSED, AWAITING, one final change


def test_simultaneous_wrong_passwords_are_counted_exactly(app, engine, actor):
    transaction_id = high(actor)
    responses = run_together([lambda c=new_client(app): actor.act(transaction_id, "VERIFY", password=WRONG, client=c) for _ in range(6)])
    assert all(not isinstance(r, Exception) for r in responses), responses
    codes = sorted(error(r) for r in responses)
    assert codes == [(403, "VERIFICATION_FAILED")] * 3 + [(409, "INVALID_STATE_TRANSITION")] * 3
    stored = db_transaction(engine, transaction_id)
    assert (stored.status, stored.verify_attempts) == (S.CANCELLED, 3)
    actions = audit_actions(engine, transaction_id)
    assert (actions.count("VERIFICATION_FAILED"), actions.count("TRANSACTION_CANCELLED")) == (3, 1)


def test_simultaneous_verify_and_cancel(app, engine, actor):
    transaction_id = high(actor)
    responses = run_together([
        lambda c=new_client(app): actor.act(transaction_id, "VERIFY", password=PASSWORD, client=c),
        lambda c=new_client(app): actor.act(transaction_id, "CANCEL", client=c),
    ])
    assert sorted(r.status_code for r in responses) == [200, 409]
    actions = audit_actions(engine, transaction_id)
    assert actions.count("TRANSACTION_APPROVED") + actions.count("TRANSACTION_CANCELLED") == 1


# ---- end to end and structure ----------------------------------------------------------------------------

def test_the_dashboard_reflects_the_outcomes(engine, client, actor):
    approved, cancelled, waiting = medium(actor), medium(actor), medium(actor)
    actor.act(approved, "CONTINUE", confirmed=True)
    actor.act(cancelled, "CANCEL")
    summary = client.get("/api/v1/dashboard/summary", headers=actor.headers(device=None)).json()
    assert summary["transactions"]["total"] == 3
    assert summary["transactions"]["by_status"] == {
        "INITIATED": 0, "ANALYSED": 0, "AWAITING_USER_ACTION": 1, "APPROVED": 1, "CANCELLED": 1, "EXPIRED": 0, "FAILED": 0,
    }
    assert (summary["transactions"]["approved_amount_paise"], summary["transactions"]["awaiting_action"]) == (500_00, 1)
    assert summary["alerts"]["unread"] == 4  # three risk warnings and one cancellation
    assert actor.get(waiting).json()["status"] == "AWAITING_USER_ACTION"


def test_every_approval_followed_an_assessment_and_an_explicit_action(engine):
    """Across everything this module did: no APPROVED row without a stored assessment, an
    approval method the assessment allowed, and a user's approval event."""
    with Session(engine) as session:
        orphans = session.execute(text(
            "SELECT count(*) FROM transactions t WHERE t.status = 'APPROVED' "
            # payments made through the API (test history inserted by fixtures has no audit trail)
            "AND EXISTS (SELECT 1 FROM audit_logs a WHERE a.transaction_id = t.id AND a.action = 'TRANSACTION_INITIATED') AND ("
            " NOT EXISTS (SELECT 1 FROM risk_assessments r WHERE r.transaction_id = t.id)"
            " OR t.approval_method IS NULL OR t.analysed_at IS NULL"
            " OR NOT EXISTS (SELECT 1 FROM audit_logs a WHERE a.transaction_id = t.id AND a.action = 'TRANSACTION_APPROVED' AND a.actor_type = 'USER')"
            " OR NOT EXISTS (SELECT 1 FROM risk_assessments r WHERE r.transaction_id = t.id AND r.allowed_actions ? "
            "   CASE t.approval_method WHEN 'CONTINUE' THEN 'CONTINUE' ELSE 'VERIFY' END))"
        )).scalar()
        approved = session.execute(text(
            "SELECT count(*) FROM transactions t WHERE t.status = 'APPROVED' AND EXISTS "
            "(SELECT 1 FROM audit_logs a WHERE a.transaction_id = t.id AND a.action = 'TRANSACTION_INITIATED')"
        )).scalar()
        high_continued = session.execute(text(
            "SELECT count(*) FROM transactions t JOIN risk_assessments r ON r.transaction_id = t.id "
            "WHERE r.risk_level = 'HIGH' AND t.approval_method = 'CONTINUE'"
        )).scalar()
    assert approved > 0 and orphans == 0 and high_continued == 0


def test_only_the_transaction_service_changes_status():
    """P-1 D4: one writer. No other application module calls the state machine or sets a status."""
    app_dir = Path(__file__).resolve().parents[1] / "app"
    callers, setters = [], []
    for path in sorted(app_dir.rglob("*.py")):
        source = path.read_text()
        name = path.relative_to(app_dir).as_posix()
        if re.search(r"\.transition\(", source):
            callers.append(name)
        if re.search(r"\.status\s*=[^=]", source):
            setters.append(name)
    assert callers == ["services/transactions.py"]
    assert setters == ["repositories/transactions.py"]  # inside TransactionRepository.transition only
