"""P-10d: POST and GET /api/v1/transactions against PostgreSQL.

Real endpoints, real commits, one throwaway schema. Covers the assessment
pipeline, the zero-score representation, idempotency (including concurrent
duplicates), ownership, limits, fail-closed behaviour, atomicity, lazy expiry
and the stale-state sweep.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.fraud_detection.ml import MLResult
from app.models import TransactionStatus
from app.repositories import AlertRepository, TransactionRepository
from app.services import transactions as transactions_service
from tests.payments_support import (
    DEVICE,
    KEY,
    TRANSACTIONS,
    Actor,
    add_payment,
    alerts_for,
    audit_actions,
    audit_trail,
    count_transactions,
    db_assessments,
    db_transaction,
    make_app,
    make_beneficiary,
    new_client,
    night_points,
    run_together,
    set_deadline,
)
from tests.pg import require_postgres_url, throwaway_schema

PG_URL = require_postgres_url()
S = TransactionStatus
NEVER_IN_A_RESPONSE = ("features_snapshot", "rule_details", "observed", "fingerprint", "request_hash", "device_id", "idempotency", "password")


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


class FixedScorer:
    """Test double for a future model, to exercise the non-rules-only paths."""

    def __init__(self, score):
        self._score = score

    def score(self, features):
        return MLResult(score=self._score, model_version="test-model-v0", details={"percentile": 0.6})


# ---- the assessment pipeline ---------------------------------------------------------------------------

def test_first_payment_is_assessed_and_waits_for_the_user(engine, actor):
    response = actor.pay(actor.beneficiary_id(), 2_500_00, description="  Rent share ")
    assert response.status_code == 201
    body = response.json()
    assessment = body["assessment"]
    night = night_points(body)

    assert (body["status"], body["amount_paise"], body["currency"], body["description"]) == ("AWAITING_USER_ACTION", 2_500_00, "INR", "Rent share")
    assert body["approval_method"] is None and body["completed_at"] is None and body["verify_attempts_remaining"] == 3
    assert body["beneficiary"]["beneficiary_name"] == "Ravi Kumar" and "****@okbank" in body["beneficiary"]["upi_id_masked"]
    window = datetime.fromisoformat(body["expires_at"]) - datetime.fromisoformat(body["initiated_at"])
    assert timedelta(minutes=10) <= window < timedelta(minutes=10, seconds=5)

    # New beneficiary (20) + first payment from this device (15), rules only.
    assert (assessment["rule_score"], assessment["final_risk_score"]) == (35 + night, 35 + night)
    assert (assessment["risk_level"], assessment["level_raised_from"]) == ("MEDIUM", None)
    assert (assessment["ml_score"], assessment["ml_available"]) == (None, False)
    assert assessment["bands"] == {"low_max": 30, "medium_max": 65}
    assert assessment["allowed_actions"] == ["CONTINUE", "VERIFY", "CANCEL"]
    assert (assessment["recommended_action"], assessment["requires_confirmation"]) == ("VERIFY", True)
    codes = [factor["code"] for factor in assessment["factors"]]
    assert codes[:2] == ["NEW_BENEFICIARY", "NEW_DEVICE"] and codes[-2:] == ["LIMITED_HISTORY", "LIMITED_ASSESSMENT"]
    assert ("UNUSUAL_TIME" in codes) == (night == 10)
    assert not any(word in response.text for word in NEVER_IN_A_RESPONSE)
    assert "fraud" not in response.text.lower()

    stored = db_transaction(engine, body["id"])
    assert stored.status == S.AWAITING_USER_ACTION and stored.analysed_at is not None
    assert len(stored.device_id_hash) == 64 and DEVICE not in stored.device_id_hash
    (row,) = db_assessments(engine, body["id"])
    assert (row.config_version, row.model_version, row.ml_score, row.ml_details) == ("risk-config-v1", None, None, None)
    assert row.features_snapshot["is_new_beneficiary"] is True and row.rule_details[-1]["summary"] is True
    assert audit_actions(engine, body["id"]) == ["TRANSACTION_INITIATED", "TRANSACTION_ASSESSED", "TRANSACTION_AWAITING_ACTION", "ML_UNAVAILABLE"]
    (alert,) = alerts_for(engine, body["id"])
    assert (alert.alert_type.value, alert.severity.value, alert.risk_assessment_id) == ("RISK_WARNING", "WARNING", row.id)
    assert alert.title == "Medium-risk payment of ₹2,500"


def test_audit_trail_records_who_what_and_the_versions(engine, actor):
    body = actor.pay(actor.beneficiary_id()).json()
    initiated, assessed, awaiting, ml = audit_trail(engine, body["id"])
    assert (initiated.actor_type.value, initiated.new_values) == ("USER", {"status": "INITIATED", "amount_paise": 500_00})
    assert initiated.user_agent and initiated.request_id  # (the test client has no IP address to truncate)
    assert assessed.actor_type.value == "SYSTEM" and assessed.old_values == {"status": "INITIATED"}
    assert assessed.new_values["status"] == "ANALYSED" and assessed.new_values["risk_level"] == "MEDIUM"
    assert assessed.event_metadata == {"config_version": "risk-config-v1", "model_version": None, "ml_available": False}
    assert awaiting.old_values == {"status": "ANALYSED"}
    assert awaiting.new_values["allowed_actions"] == ["CONTINUE", "VERIFY", "CANCEL"] and awaiting.new_values["recommended_action"] == "VERIFY"
    assert ml.event_metadata == {"reason": "MODEL_NOT_IMPLEMENTED", "mode": "rules_only"}
    assert all(entry.user_id == actor.id and entry.entity_type == "transaction" for entry in (initiated, assessed, awaiting, ml))


def test_no_rule_fired_is_stored_as_score_zero_level_medium(engine, actor):
    """Rules-only, nothing unusual: the score stays 0 (no points invented); the level is MEDIUM."""
    response = actor.pay(actor.established(), 500_00)
    assessment = response.json()["assessment"]
    assert (assessment["rule_score"], assessment["ml_score"], assessment["final_risk_score"]) == (0, None, 0)
    assert (assessment["risk_level"], assessment["level_raised_from"], assessment["ml_available"]) == ("MEDIUM", "LOW", False)
    assert [factor["code"] for factor in assessment["factors"]] == ["LIMITED_ASSESSMENT"]
    assert assessment["allowed_actions"] == ["CONTINUE", "VERIFY", "CANCEL"]
    (row,) = db_assessments(engine, response.json()["id"])
    assert (row.rule_score, row.ml_score, row.final_risk_score, row.risk_level.value, row.model_version) == (0, None, 0, "MEDIUM", None)
    assert row.rule_details == [{
        "summary": True, "raw_points_total": 0, "rule_score": 0, "band_level": "LOW", "risk_level": "MEDIUM",
        "level_raised_from": "LOW", "ml_unavailable_reason": "MODEL_NOT_IMPLEMENTED",
        "bands": {"low_max": 30, "medium_max": 65}, "recommended_action": "VERIFY", "requires_confirmation": True,
    }]


def test_large_first_payment_is_high_risk(engine, actor):
    response = actor.pay(actor.beneficiary_id(), 30_000_00)
    body = response.json()
    night = night_points(body)
    assessment = body["assessment"]
    # New beneficiary 20 + large for a new account 25 + new device 15 + large first payment to a new payee 15.
    assert (assessment["final_risk_score"], assessment["risk_level"]) == (75 + night, "HIGH")
    assert (assessment["allowed_actions"], assessment["recommended_action"], assessment["requires_confirmation"]) == (["VERIFY", "CANCEL"], "CANCEL", False)
    (alert,) = alerts_for(engine, body["id"])
    assert (alert.severity.value, alert.title) == ("CRITICAL", "High-risk payment of ₹30,000")


def test_with_a_model_a_low_score_stays_low(app, engine, actor):
    app.state.anomaly_scorer = FixedScorer(10)
    body = actor.pay(actor.established(), 500_00).json()
    assessment = body["assessment"]
    assert (assessment["rule_score"], assessment["ml_score"], assessment["final_risk_score"]) == (0, 10, 4)
    assert (assessment["risk_level"], assessment["level_raised_from"], assessment["ml_available"]) == ("LOW", None, True)
    assert (assessment["allowed_actions"], assessment["recommended_action"], assessment["requires_confirmation"]) == (["CONTINUE", "CANCEL"], "CONTINUE", False)
    assert "ML_UNAVAILABLE" not in audit_actions(engine, body["id"]) and alerts_for(engine, body["id"]) == []
    assert db_assessments(engine, body["id"])[0].model_version == "test-model-v0"


def test_a_crashing_model_falls_back_to_rules_only(app, engine, actor):
    class Broken:
        def score(self, features):
            raise RuntimeError("model file corrupt")

    app.state.anomaly_scorer = Broken()
    body = actor.pay(actor.beneficiary_id()).json()
    assert body["status"] == "AWAITING_USER_ACTION" and body["assessment"]["ml_available"] is False
    assert audit_trail(engine, body["id"])[-1].event_metadata == {"reason": "SCORER_ERROR:RuntimeError", "mode": "rules_only"}


# ---- idempotency ---------------------------------------------------------------------------------------

def test_same_key_and_body_returns_the_stored_payment(engine, actor):
    beneficiary = actor.beneficiary_id()
    first = actor.pay(beneficiary, 700_00, key="retry-key-0001")
    again = actor.pay(beneficiary, 700_00, key="retry-key-0001")
    assert (first.status_code, again.status_code) == (201, 200)
    first_body, again_body = first.json(), again.json()
    first_body.pop("server_time"), again_body.pop("server_time")
    assert again_body == first_body
    assert count_transactions(engine, actor.id) == 1 and len(db_assessments(engine, first_body["id"])) == 1
    assert audit_actions(engine, first_body["id"]).count("TRANSACTION_INITIATED") == 1
    assert len(alerts_for(engine, first_body["id"])) == 1


def test_same_key_with_a_different_body_is_rejected(engine, actor):
    beneficiary = actor.beneficiary_id()
    assert actor.pay(beneficiary, 700_00, key="reused-key-0001").status_code == 201
    for change in ({"amount_paise": 700_01}, {"description": "different"}, {"transaction_type": "P2M"}):
        response = actor.pay(beneficiary, **{"amount_paise": 700_00, **change}, key="reused-key-0001")
        assert response.status_code == 409 and response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert count_transactions(engine, actor.id) == 1


def test_keys_are_scoped_to_the_user(engine, client, actor):
    other = Actor(engine, client)
    mine = actor.pay(actor.beneficiary_id(), key="shared-key-0001")
    theirs = other.pay(other.beneficiary_id(), key="shared-key-0001")
    assert (mine.status_code, theirs.status_code) == (201, 201) and mine.json()["id"] != theirs.json()["id"]


def test_concurrent_duplicates_create_exactly_one_payment(app, engine, actor):
    beneficiary = actor.beneficiary_id()
    clients = [new_client(app) for _ in range(8)]
    responses = run_together([lambda c=c: actor.pay(beneficiary, 900_00, key="double-click-0001", client=c) for c in clients])
    assert all(not isinstance(r, Exception) for r in responses), responses
    assert sorted(r.status_code for r in responses) == [200] * 7 + [201]
    assert len({r.json()["id"] for r in responses}) == 1
    transaction_id = responses[0].json()["id"]
    assert count_transactions(engine, actor.id) == 1
    assert len(db_assessments(engine, transaction_id)) == 1
    assert audit_actions(engine, transaction_id).count("TRANSACTION_INITIATED") == 1
    assert audit_actions(engine, transaction_id).count("TRANSACTION_ASSESSED") == 1
    # A duplicate that arrived mid-assessment waited for it; none saw a half-assessed payment.
    assert {r.json()["status"] for r in responses} <= {"AWAITING_USER_ACTION", "INITIATED"}
    assert actor.get(transaction_id).json()["status"] == "AWAITING_USER_ACTION"


def test_different_keys_are_separate_payments_and_the_repeat_is_flagged(actor):
    beneficiary = actor.beneficiary_id()
    first = actor.pay(beneficiary, 800_00).json()
    second = actor.pay(beneficiary, 800_00).json()
    assert first["id"] != second["id"]
    velocity = [f for f in second["assessment"]["factors"] if f["code"] == "HIGH_VELOCITY"]
    assert velocity and velocity[0]["detail"] == "Same beneficiary and amount as a payment attempt a few minutes ago"


# ---- validation, limits and ownership ------------------------------------------------------------------

@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"amount_paise": 99}, "VALIDATION_ERROR"),  # below Rs 1
        ({"amount_paise": 0}, "VALIDATION_ERROR"),
        ({"amount_paise": -500_00}, "VALIDATION_ERROR"),
        ({"amount_paise": 100.5}, "VALIDATION_ERROR"),  # money is integer paise
        ({"amount_paise": "50000"}, "VALIDATION_ERROR"),
        ({"amount_paise": True}, "VALIDATION_ERROR"),
        ({"amount_paise": 1_00_000_00 + 1}, "AMOUNT_OUT_OF_RANGE"),
        ({"description": "x" * 81}, "VALIDATION_ERROR"),
        ({"description": "line\nbreak"}, "VALIDATION_ERROR"),
        ({"transaction_type": "WIRE"}, "VALIDATION_ERROR"),
        ({"status": "APPROVED"}, "VALIDATION_ERROR"),  # clients cannot send state
        ({"risk_level": "LOW"}, "VALIDATION_ERROR"),
        ({"user_id": str(uuid.uuid4())}, "VALIDATION_ERROR"),
    ],
)
def test_invalid_requests_create_nothing(engine, actor, change, code):
    response = actor.pay(actor.beneficiary_id(), **{"amount_paise": 500_00, **change})
    assert response.status_code == 422 and response.json()["error"]["code"] == code
    assert count_transactions(engine, actor.id) == 0


def test_amount_limits_are_inclusive(actor):
    beneficiary = actor.beneficiary_id()
    assert actor.pay(beneficiary, 100).status_code == 201  # Rs 1
    assert actor.pay(beneficiary, 1_00_000_00).status_code == 201  # Rs 1,00,000
    response = actor.pay(beneficiary, 1_00_000_01)
    assert response.json()["error"]["message"] == "The most you can send in one simulated payment is ₹1,00,000."


@pytest.mark.parametrize(
    "headers",
    [{"key": None}, {"device": None}, {"key": "short"}, {"key": "k" * 129}, {"key": "has spaces in it"}, {"device": "x"}],
)
def test_idempotency_key_and_device_id_are_required(engine, client, actor, headers):
    beneficiary = actor.beneficiary_id()
    settings = {"key": "valid-key-0001", "device": DEVICE, **headers}
    response = client.post(TRANSACTIONS, json={"beneficiary_id": beneficiary, "amount_paise": 500_00}, headers=actor.headers(**settings))
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert count_transactions(engine, actor.id) == 0


def test_requires_authentication(client):
    response = client.post(TRANSACTIONS, json={"beneficiary_id": str(uuid.uuid4()), "amount_paise": 500_00},
                           headers={"Idempotency-Key": "valid-key-0001", "X-Device-Id": DEVICE})
    assert response.status_code == 401
    assert client.get(f"{TRANSACTIONS}/{uuid.uuid4()}").status_code == 401


def test_the_beneficiary_must_be_your_own_and_active(engine, client, actor):
    other = Actor(engine, client)
    theirs = other.beneficiary_id()
    mine = actor.beneficiary_id()
    with Session(engine) as session:
        session.execute(text("UPDATE beneficiaries SET is_active = false WHERE id = :id"), {"id": uuid.UUID(mine)})
        session.commit()
    for beneficiary in (theirs, mine, str(uuid.uuid4())):
        response = actor.pay(beneficiary)
        assert response.status_code == 404 and response.json()["error"]["code"] == "BENEFICIARY_NOT_FOUND"
    assert count_transactions(engine, actor.id) == 0 and count_transactions(engine, other.id) == 0


def test_reading_is_limited_to_the_owner(engine, client, actor):
    other = Actor(engine, client)
    body = actor.pay(actor.beneficiary_id()).json()
    mine = actor.get(body["id"])
    assert mine.status_code == 200 and mine.json()["assessment"] == body["assessment"]
    for response in (other.get(body["id"]), actor.get(uuid.uuid4())):
        assert response.status_code == 404 and response.json()["error"]["code"] == "TRANSACTION_NOT_FOUND"
    assert client.get(f"{TRANSACTIONS}/not-a-uuid", headers=actor.headers(device=None)).status_code == 422


# ---- fail closed and atomic ------------------------------------------------------------------------------

def test_if_assessment_fails_the_payment_is_failed_never_approved(engine, actor, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("rule engine exploded")

    monkeypatch.setattr(transactions_service, "assess", broken)
    response = actor.pay(actor.beneficiary_id())
    assert response.status_code == 201
    body = response.json()
    assert (body["status"], body["assessment"], body["approval_method"]) == ("FAILED", None, None)
    assert body["completed_at"] is not None

    assert db_assessments(engine, body["id"]) == []
    assert audit_actions(engine, body["id"]) == ["TRANSACTION_INITIATED", "TRANSACTION_FAILED"]
    failed = audit_trail(engine, body["id"])[-1]
    assert failed.new_values == {"status": "FAILED", "reason": "assessment_error"} and failed.event_metadata == {"error_type": "RuntimeError"}
    (alert,) = alerts_for(engine, body["id"])
    assert alert.message == "We could not assess this payment, so it was not sent. Nothing was paid."

    for action in ({"action": "CONTINUE", "confirmed": True}, {"action": "VERIFY", "password": "x"}, {"action": "CANCEL"}):
        refused = actor.act(body["id"], **action)
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert db_transaction(engine, body["id"]).status == S.FAILED


@pytest.mark.parametrize("failing_step", ["assessment", "awaiting", "audit", "alert"])
def test_assessment_is_all_or_nothing(engine, actor, monkeypatch, failing_step):
    """A failure at any step after INITIATED leaves no assessment, no later audit row and no
    risk alert behind: the payment is FAILED, with only its own failure records."""
    if failing_step == "assessment":
        monkeypatch.setattr(transactions_service.RiskAssessmentRepository, "create", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    elif failing_step == "awaiting":
        original = TransactionRepository.transition

        def transition(self, transaction, to_status, **kwargs):
            if to_status == S.AWAITING_USER_ACTION:
                raise RuntimeError("boom")
            return original(self, transaction, to_status, **kwargs)

        monkeypatch.setattr(TransactionRepository, "transition", transition)
    elif failing_step == "audit":
        original_audit = transactions_service.TransactionService._audit_system

        def audit(self, action, transaction, **kwargs):
            if action == "ML_UNAVAILABLE":
                raise RuntimeError("boom")
            return original_audit(self, action, transaction, **kwargs)

        monkeypatch.setattr(transactions_service.TransactionService, "_audit_system", audit)
    else:
        original_alert = AlertRepository.create

        def create(self, **kwargs):
            if kwargs["alert_type"].value == "RISK_WARNING":
                raise RuntimeError("boom")
            return original_alert(self, **kwargs)

        monkeypatch.setattr(AlertRepository, "create", create)

    body = actor.pay(actor.beneficiary_id()).json()
    assert body["status"] == "FAILED" and body["assessment"] is None
    assert db_assessments(engine, body["id"]) == []
    assert audit_actions(engine, body["id"]) == ["TRANSACTION_INITIATED", "TRANSACTION_FAILED"]
    assert [alert.alert_type.value for alert in alerts_for(engine, body["id"])] == ["TRANSACTION_FAILED"]
    stored = db_transaction(engine, body["id"])
    assert (stored.status, stored.analysed_at, stored.expires_at, stored.approval_method) == (S.FAILED, None, None, None)


def test_a_failed_attempt_can_be_followed_by_a_fresh_one(engine, actor, monkeypatch):
    beneficiary = actor.beneficiary_id()
    with monkeypatch.context() as patch:
        patch.setattr(transactions_service, "assess", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        failed = actor.pay(beneficiary, key="attempt-key-0001").json()
    assert failed["status"] == "FAILED"
    assert actor.pay(beneficiary, key="attempt-key-0001").json()["status"] == "FAILED"  # the same key replays the failure
    assert actor.pay(beneficiary, key="attempt-key-0002").json()["status"] == "AWAITING_USER_ACTION"


def test_without_the_hash_key_no_payment_is_created(engine, app, actor):
    beneficiary = actor.beneficiary_id()
    app.state.settings = app.state.settings.model_copy(update={"IDENTIFIER_HASH_KEY": None})
    response = actor.pay(beneficiary)
    assert response.status_code == 500 and response.json()["error"]["code"] == "CONFIGURATION_ERROR"
    assert count_transactions(engine, actor.id) == 0


# ---- lazy expiry and the stale-state sweep ----------------------------------------------------------------

def test_reading_a_payment_past_its_deadline_expires_it(engine, actor):
    body = actor.pay(actor.beneficiary_id()).json()
    set_deadline(engine, body["id"], seconds_from_now=-1)
    read = actor.get(body["id"]).json()
    assert (read["status"], read["approval_method"]) == ("EXPIRED", None) and read["completed_at"] is not None
    assert read["assessment"]["final_risk_score"] == body["assessment"]["final_risk_score"]  # the assessment is kept
    trail = audit_trail(engine, body["id"])
    assert (trail[-1].action, trail[-1].actor_type.value, trail[-1].new_values) == ("TRANSACTION_EXPIRED", "SYSTEM", {"status": "EXPIRED"})
    assert alerts_for(engine, body["id"])[-1].message == "No action was taken within 10 minutes, so the simulated payment was not sent. Nothing was paid."
    assert actor.get(body["id"]).json()["status"] == "EXPIRED" and audit_actions(engine, body["id"]).count("TRANSACTION_EXPIRED") == 1


def test_a_payment_still_inside_its_deadline_is_not_expired(engine, actor):
    body = actor.pay(actor.beneficiary_id()).json()
    set_deadline(engine, body["id"], seconds_from_now=30)
    assert actor.get(body["id"]).json()["status"] == "AWAITING_USER_ACTION"


def stale_attempt(engine, actor, *, minutes_ago):
    with Session(engine, expire_on_commit=False) as session:
        beneficiary = make_beneficiary(session, actor.user)
        txn = add_payment(session, actor.user, beneficiary, 100_00, at=datetime.now(UTC) - timedelta(minutes=minutes_ago), status=S.INITIATED)
        session.commit()
        return txn.id


def test_reading_an_abandoned_attempt_fails_it(engine, actor):
    fresh, stale = stale_attempt(engine, actor, minutes_ago=1), stale_attempt(engine, actor, minutes_ago=3)
    assert actor.get(fresh).json()["status"] == "INITIATED"
    read = actor.get(stale).json()
    assert (read["status"], read["assessment"]) == ("FAILED", None)
    assert audit_trail(engine, stale)[-1].new_values == {"status": "FAILED", "reason": "assessment_abandoned"}


def test_creating_a_payment_sweeps_overdue_payments_of_any_user(engine, client, actor):
    other = Actor(engine, client)
    overdue = other.pay(other.beneficiary_id()).json()["id"]
    waiting = other.pay(other.beneficiary_id("Second")).json()["id"]
    set_deadline(engine, overdue, seconds_from_now=-5)
    stale, fresh = stale_attempt(engine, other, minutes_ago=5), stale_attempt(engine, other, minutes_ago=1)

    assert actor.pay(actor.beneficiary_id()).status_code == 201

    assert db_transaction(engine, overdue).status == S.EXPIRED and audit_actions(engine, overdue)[-1] == "TRANSACTION_EXPIRED"
    assert db_transaction(engine, stale).status == S.FAILED and audit_actions(engine, stale)[-1] == "TRANSACTION_FAILED"
    assert db_transaction(engine, waiting).status == S.AWAITING_USER_ACTION
    assert db_transaction(engine, fresh).status == S.INITIATED
    assert alerts_for(engine, overdue)[-1].alert_type.value == "TRANSACTION_EXPIRED"
    assert alerts_for(engine, overdue)[-1].user_id == other.id  # the alert goes to the payment's owner


def test_the_sweep_skips_rows_another_request_has_locked(engine, client, actor):
    other = Actor(engine, client)
    overdue = other.pay(other.beneficiary_id()).json()["id"]
    set_deadline(engine, overdue, seconds_from_now=-5)
    with Session(engine) as holder:
        holder.execute(text("SELECT id FROM transactions WHERE id = :id FOR UPDATE"), {"id": uuid.UUID(overdue)})
        response = actor.pay(actor.beneficiary_id())  # must not wait for the held lock
        assert response.status_code == 201
        holder.rollback()
    assert db_transaction(engine, overdue).status == S.AWAITING_USER_ACTION  # left for its own request or the next sweep


def test_a_sweep_failure_does_not_block_the_payment(engine, actor, monkeypatch):
    monkeypatch.setattr(TransactionRepository, "lock_expired_awaiting", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert actor.pay(actor.beneficiary_id()).json()["status"] == "AWAITING_USER_ACTION"


# ---- privacy ------------------------------------------------------------------------------------------------

def test_stored_json_never_contains_identifiers_or_secrets(engine, actor):
    body = actor.pay(actor.beneficiary_id()).json()
    (row,) = db_assessments(engine, body["id"])
    stored = json.dumps([row.rule_details, row.explanation, row.features_snapshot]) + json.dumps(
        [[e.old_values, e.new_values, e.event_metadata] for e in audit_trail(engine, body["id"])]
    )
    assert DEVICE not in stored and "okbank" not in stored and actor.token not in stored
    assert db_transaction(engine, body["id"]).device_id_hash != DEVICE
    from app.utils.privacy import hash_device_id

    assert db_transaction(engine, body["id"]).device_id_hash == hash_device_id(DEVICE, KEY)


# ---- observability (P-1: request_id, assessment latency, ml_available and outcome) -------------------------

def assessment_logs(caplog):
    return [record for record in caplog.records if record.name == "sakshampay.transactions" and record.getMessage() == "Payment assessed"]


def test_each_assessment_is_logged_with_latency_ml_availability_and_outcome(actor, caplog):
    with caplog.at_level("INFO", logger="sakshampay.transactions"):
        body = actor.pay(actor.beneficiary_id(), 1_234_56).json()
    (record,) = assessment_logs(caplog)
    assert (record.transaction_id, record.ml_available, record.risk_level, record.outcome) == (body["id"], False, "MEDIUM", "AWAITING_USER_ACTION")
    assert isinstance(record.assessment_ms, float) and record.assessment_ms >= 0
    assert record.request_id  # added by the logging setup
    logged = str(record.__dict__)
    assert "123456" not in logged and "1,234" not in logged and DEVICE not in logged and "okbank" not in logged


def test_a_failed_assessment_is_logged_with_its_outcome(actor, caplog, monkeypatch):
    monkeypatch.setattr(transactions_service, "assess", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with caplog.at_level("INFO", logger="sakshampay.transactions"):
        body = actor.pay(actor.beneficiary_id()).json()
    (record,) = assessment_logs(caplog)
    assert (record.transaction_id, record.ml_available, record.risk_level, record.outcome) == (body["id"], None, None, "FAILED")


def test_a_replay_is_not_logged_as_a_new_assessment(actor, caplog):
    beneficiary = actor.beneficiary_id()
    actor.pay(beneficiary, key="log-replay-0001")
    caplog.clear()
    with caplog.at_level("INFO", logger="sakshampay.transactions"):
        assert actor.pay(beneficiary, key="log-replay-0001").status_code == 200
    assert assessment_logs(caplog) == []
