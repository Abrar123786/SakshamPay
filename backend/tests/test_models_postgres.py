"""P-4 constraints exercised against a real PostgreSQL server.

Runs only when TEST_DATABASE_URL is set. The tables are created in a throwaway
schema with ``metadata.create_all`` (test scaffolding, not a migration; migrations
arrive in P-5) and the schema is dropped afterwards. Each test runs inside a
transaction that is rolled back.
"""

import itertools
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

import app.models as models
from app.core.config import Settings
from app.models import (
    AlertSeverity,
    AlertType,
    ApprovalMethod,
    AuditActorType,
    Base,
    ImmutableRecordError,
    RiskLevel,
    TransactionStatus,
    TransactionType,
    compute_final_risk_score,
)

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("TEST_DATABASE_URL not set; skipping PostgreSQL model tests", allow_module_level=True)

ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHRzYWx0$" + "h" * 43
NOW = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def engine():
    raw_url = os.environ["TEST_DATABASE_URL"]
    url = Settings(_env_file=None, APP_ENV="test", DATABASE_URL=raw_url).DATABASE_URL.get_secret_value()
    schema = f"p4_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    with admin.begin() as conn:
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


@pytest.fixture
def session(engine):
    connection = engine.connect()
    outer = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield db
    db.close()
    outer.rollback()
    connection.close()


# --- factories -----------------------------------------------------------------------------

def hex64(seed: str) -> str:
    return (uuid.uuid5(uuid.NAMESPACE_DNS, seed).hex * 2)[:64]


def add_user(db, email="asha@example.com", **kw):
    user = models.User(full_name="Asha Rao", email=email, password_hash=ARGON2_HASH, **kw)
    db.add(user)
    db.flush()
    return user


def add_beneficiary(db, user, seed="acct-1", **kw):
    values = dict(
        beneficiary_name="Ravi Kumar",
        bank_name="Example Bank",
        account_reference_masked="XXXXXXXX4321",
        account_reference_fingerprint=hex64(seed),
    )
    values.update(kw)
    beneficiary = models.Beneficiary(user=user, **values)
    db.add(beneficiary)
    db.flush()
    return beneficiary


def add_transaction(db, user, beneficiary, key="idem-key-0001", **kw):
    values = dict(
        user_id=user.id,
        beneficiary_id=beneficiary.id,
        amount_paise=4_800_000,
        transaction_type=TransactionType.P2P,
        idempotency_key=key,
        request_hash=hex64(key),
        initiated_at=NOW,
    )
    values.update(kw)
    transaction = models.Transaction(**values)
    db.add(transaction)
    db.flush()
    return transaction


def add_assessment(db, transaction, rule=70, ml=82, **kw):
    values = dict(
        transaction_id=transaction.id,
        rule_score=rule,
        ml_score=ml,
        final_risk_score=compute_final_risk_score(rule, ml),
        risk_level=RiskLevel.HIGH,
        model_version="iforest-2026.11.01" if ml is not None else None,
        config_version="risk-config-1",
        rule_details=[{"rule": "R1", "points": 20}],
        ml_details={"raw_anomaly": 0.61, "percentile": 0.993} if ml is not None else None,
        explanation=[{"code": "NEW_BENEFICIARY", "label": "First payment to this beneficiary"}],
        features_snapshot={"amount_z_user": 3.4},
        allowed_actions=["CANCEL", "VERIFY"],
    )
    values.update(kw)
    assessment = models.RiskAssessment(**values)
    db.add(assessment)
    db.flush()
    return assessment


def rejected(db, constraint: str, action):
    """Run ``action`` (which flushes) and assert PostgreSQL rejects it via ``constraint``."""
    with pytest.raises(IntegrityError) as exc_info:
        with db.begin_nested():  # roll back only this attempt, keep earlier rows of the test
            action()
            db.flush()
    assert constraint in str(exc_info.value.orig), str(exc_info.value.orig)


# --- schema exists ---------------------------------------------------------------------------

def test_all_six_tables_are_created(session):
    names = set(session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")).scalars())
    assert names == {"users", "beneficiaries", "transactions", "risk_assessments", "alerts", "audit_logs"}


# --- happy path and relationships -------------------------------------------------------------

def test_full_lifecycle_and_relationships(session):
    user = add_user(session)
    beneficiary = add_beneficiary(session, user)
    txn = add_transaction(session, user, beneficiary)
    assert txn.status is TransactionStatus.INITIATED and txn.version == 1 and txn.currency == "INR"

    assessment = add_assessment(session, txn)
    txn.status = TransactionStatus.AWAITING_USER_ACTION
    txn.analysed_at = NOW + timedelta(seconds=1)
    txn.expires_at = NOW + timedelta(minutes=10)
    session.flush()
    txn.status = TransactionStatus.APPROVED
    txn.approval_method = ApprovalMethod.VERIFIED
    txn.completed_at = NOW + timedelta(minutes=2)
    session.flush()
    assert txn.version == 3

    alert = models.Alert(
        user=user,
        transaction_id=txn.id,
        risk_assessment_id=assessment.id,
        alert_type=AlertType.RISK_WARNING,
        severity=AlertSeverity.WARNING,
        title="High-risk payment",
        message="This payment looked unusual.",
    )
    log = models.AuditLog(
        user_id=user.id,
        transaction_id=txn.id,
        actor_type=AuditActorType.USER,
        action="TRANSACTION_STATUS_CHANGED",
        entity_type="transaction",
        entity_id=txn.id,
        old_values={"status": "AWAITING_USER_ACTION"},
        new_values={"status": "APPROVED"},
        ip_address="203.0.113.0/24",
    )
    session.add_all([alert, log])
    session.flush()
    session.expire_all()

    loaded = session.get(models.Transaction, txn.id)
    assert loaded.user.email == "asha@example.com"
    assert loaded.beneficiary.id == beneficiary.id
    assert loaded.risk_assessment.final_risk_score == 75
    assert loaded.alerts[0].risk_assessment.id == assessment.id
    assert beneficiary.transactions[0].id == txn.id
    assert [a.id for a in user.alerts] == [alert.id]
    assert log.id is not None and log.transaction.id == txn.id
    assert str(session.get(models.AuditLog, log.id).ip_address) == "203.0.113.0/24"


def test_server_defaults_and_updated_at(session):
    user = add_user(session)
    assert user.is_active is True and user.failed_login_count == 0
    created, updated = user.created_at, user.updated_at
    assert created.tzinfo is not None
    session.execute(text("SELECT pg_sleep(0.01)"))
    user.full_name = "Asha R"
    session.flush()
    session.refresh(user)
    assert user.updated_at >= updated and user.created_at == created


# --- users --------------------------------------------------------------------------------------

def test_plaintext_password_is_rejected(session):
    rejected(session, "ck_users_password_hash_argon2id",
             lambda: session.add(models.User(full_name="X", email="x@example.com", password_hash="hunter2")))


def test_email_is_unique_and_lowercase(session):
    add_user(session, email="dup@example.com")
    rejected(session, "uq_users_email", lambda: add_user(session, email="dup@example.com"))
    rejected(session, "ck_users_email_lowercase", lambda: add_user(session, email="Upper@Example.com"))


def test_phone_is_e164_and_unique_when_present(session):
    add_user(session, email="a@example.com", phone_number="+919876543210")
    add_user(session, email="b@example.com")  # NULL phone: allowed for many users
    add_user(session, email="c@example.com")
    rejected(session, "uq_users_phone_number",
             lambda: add_user(session, email="d@example.com", phone_number="+919876543210"))
    rejected(session, "ck_users_phone_e164", lambda: add_user(session, email="e@example.com", phone_number="98765 43210"))


# --- beneficiaries ---------------------------------------------------------------------------------

def test_duplicate_beneficiary_for_same_user_is_rejected(session):
    user = add_user(session)
    add_beneficiary(session, user, seed="same-account")
    rejected(session, "uq_beneficiaries_user_id_account_reference_fingerprint",
             lambda: add_beneficiary(session, user, seed="same-account"))


def test_same_account_may_be_saved_by_different_users(session):
    add_beneficiary(session, add_user(session, email="one@example.com"), seed="shared")
    add_beneficiary(session, add_user(session, email="two@example.com"), seed="shared")


def test_beneficiary_needs_an_identifier_and_paired_fields(session):
    user = add_user(session)
    rejected(session, "ck_beneficiaries_has_payment_identifier", lambda: add_beneficiary(
        session, user, account_reference_masked=None, account_reference_fingerprint=None))
    rejected(session, "ck_beneficiaries_upi_id_pair",
             lambda: add_beneficiary(session, user, seed="u2", upi_id_masked="ra****@okaxis"))


# --- transactions -----------------------------------------------------------------------------------

@pytest.mark.parametrize(("amount", "constraint"), [(0, "ck_transactions_amount_positive"), (-100, "ck_transactions_amount_positive")])
def test_invalid_amounts_are_rejected(session, amount, constraint):
    user = add_user(session)
    beneficiary = add_beneficiary(session, user)
    rejected(session, constraint, lambda: add_transaction(session, user, beneficiary, amount_paise=amount))


def test_large_amounts_fit_bigint_paise(session):
    user = add_user(session)
    txn = add_transaction(session, user, add_beneficiary(session, user), amount_paise=10_000_000_000)  # Rs 10 crore
    assert txn.amount_paise == 10_000_000_000


def test_only_inr_is_accepted(session):
    user = add_user(session)
    beneficiary = add_beneficiary(session, user)
    rejected(session, "ck_transactions_currency_inr", lambda: add_transaction(session, user, beneficiary, currency="USD"))


def test_idempotency_key_is_unique_per_user_only(session):
    alice = add_user(session, email="alice@example.com")
    bob = add_user(session, email="bob@example.com")
    alice_ben = add_beneficiary(session, alice)
    add_transaction(session, alice, alice_ben, key="shared-key-123")
    add_transaction(session, bob, add_beneficiary(session, bob), key="shared-key-123")  # other user: fine
    rejected(session, "uq_transactions_user_id_idempotency_key",
             lambda: add_transaction(session, alice, alice_ben, key="shared-key-123"))


def test_cannot_pay_another_users_beneficiary(session):
    alice = add_user(session, email="alice@example.com")
    bob = add_user(session, email="bob@example.com")
    bobs_payee = add_beneficiary(session, bob)
    rejected(session, "fk_transactions_beneficiary_id_user_id_beneficiaries",
             lambda: add_transaction(session, alice, bobs_payee))


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        ({"status": TransactionStatus.APPROVED, "completed_at": NOW, "approval_method": ApprovalMethod.CONTINUE},
         "ck_transactions_analysed_at_required"),
        ({"status": TransactionStatus.APPROVED, "analysed_at": NOW, "completed_at": NOW},
         "ck_transactions_approval_method_matches_status"),
        ({"status": TransactionStatus.AWAITING_USER_ACTION, "analysed_at": NOW},
         "ck_transactions_expires_at_required"),
        ({"status": TransactionStatus.CANCELLED, "analysed_at": NOW},
         "ck_transactions_completed_at_matches_status"),
        ({"status": TransactionStatus.FAILED, "completed_at": NOW - timedelta(hours=1)},
         "ck_transactions_timestamps_ordered"),
        ({"verify_attempts": 4}, "ck_transactions_verify_attempts_range"),
        ({"status": "SETTLED"}, "ck_transactions_status"),
    ],
)
def test_lifecycle_constraints(session, changes, constraint):
    user = add_user(session)
    beneficiary = add_beneficiary(session, user)
    if changes.get("status") == "SETTLED":
        # bypass the ORM enum to prove the database itself rejects unknown states
        txn = add_transaction(session, user, beneficiary)
        rejected(session, constraint, lambda: session.execute(
            text("UPDATE transactions SET status = 'SETTLED' WHERE id = :id"), {"id": txn.id}))
        return
    rejected(session, constraint, lambda: add_transaction(session, user, beneficiary, **changes))


def test_optimistic_lock_detects_concurrent_change(session):
    user = add_user(session)
    txn = add_transaction(session, user, add_beneficiary(session, user))
    session.execute(text("UPDATE transactions SET version = version + 1 WHERE id = :id"), {"id": txn.id})
    txn.verify_attempts = 1
    with pytest.raises(StaleDataError):
        session.flush()
    session.rollback()


# --- risk assessments --------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("kwargs", "constraint"),
    [
        ({"rule": 101, "ml": 50}, "ck_risk_assessments_rule_score_range"),
        ({"rule": 50, "ml": -1}, "ck_risk_assessments_ml_score_range"),
        ({"rule": 50, "ml": 50, "final_risk_score": 51}, "ck_risk_assessments_final_score_formula"),
        ({"rule": 40, "ml": None, "final_risk_score": 30}, "ck_risk_assessments_final_score_formula"),
        ({"rule": 40, "ml": None, "model_version": "iforest-1"}, "ck_risk_assessments_model_version_matches_ml"),
        ({"rule": 40, "ml": 10, "allowed_actions": []}, "ck_risk_assessments_allowed_actions_non_empty"),
        ({"rule": 40, "ml": 10, "explanation": {"not": "a list"}}, "ck_risk_assessments_explanation_array"),
    ],
)
def test_invalid_assessments_are_rejected(session, kwargs, constraint):
    user = add_user(session)
    txn = add_transaction(session, user, add_beneficiary(session, user))
    rejected(session, constraint, lambda: add_assessment(session, txn, **kwargs))


def test_rules_only_assessment_is_valid(session):
    user = add_user(session)
    txn = add_transaction(session, user, add_beneficiary(session, user))
    assessment = add_assessment(session, txn, rule=40, ml=None, risk_level=RiskLevel.MEDIUM)
    assert assessment.final_risk_score == 40 and assessment.model_version is None


def test_one_assessment_per_transaction(session):
    user = add_user(session)
    txn = add_transaction(session, user, add_beneficiary(session, user))
    add_assessment(session, txn)
    rejected(session, "uq_risk_assessments_transaction_id", lambda: add_assessment(session, txn))


def test_database_formula_matches_python_for_every_score_pair(session):
    rows = session.execute(text(
        "SELECT r, m, round((3 * r + 2 * m)::numeric / 5)::int "
        "FROM generate_series(0, 100) r CROSS JOIN generate_series(0, 100) m"
    )).all()
    assert len(rows) == 101 * 101
    assert all(final == compute_final_risk_score(r, m) for r, m, final in rows)
    assert all(abs(compute_final_risk_score(r, m) - (0.6 * r + 0.4 * m)) <= 0.4 + 1e-9
               for r, m in itertools.product(range(0, 101, 7), repeat=2))


def test_risk_assessment_is_append_only(session):
    user = add_user(session)
    assessment = add_assessment(session, add_transaction(session, user, add_beneficiary(session, user)))
    assessment.risk_level = RiskLevel.LOW
    with pytest.raises(ImmutableRecordError):
        session.flush()
    session.rollback()


# --- alerts ---------------------------------------------------------------------------------------------

def _two_transactions(session):
    user = add_user(session)
    beneficiary = add_beneficiary(session, user)
    first = add_transaction(session, user, beneficiary, key="first-key-001")
    second = add_transaction(session, user, beneficiary, key="second-key-002")
    return user, first, second


def _alert(user, **kw):
    return models.Alert(user_id=user.id, alert_type=AlertType.RISK_WARNING, severity=AlertSeverity.WARNING,
                        title="Check this payment", message="Unusual amount.", **kw)


def test_alert_assessment_must_belong_to_alert_transaction(session):
    user, first, second = _two_transactions(session)
    assessment_of_first = add_assessment(session, first)
    rejected(session, "fk_alerts_risk_assessment_id_transaction_id_risk_assessments",
             lambda: session.add(_alert(user, transaction_id=second.id, risk_assessment_id=assessment_of_first.id)))


def test_alert_assessment_requires_transaction(session):
    user, first, _ = _two_transactions(session)
    assessment = add_assessment(session, first)
    rejected(session, "ck_alerts_assessment_requires_transaction",
             lambda: session.add(_alert(user, risk_assessment_id=assessment.id)))


def test_alert_transaction_must_belong_to_alert_user(session):
    _, first, _ = _two_transactions(session)
    other = add_user(session, email="other@example.com")
    rejected(session, "fk_alerts_transaction_id_user_id_transactions",
             lambda: session.add(_alert(other, transaction_id=first.id)))


def test_alert_read_state_is_consistent(session):
    user, _, _ = _two_transactions(session)
    rejected(session, "ck_alerts_read_at_matches_is_read", lambda: session.add(_alert(user, is_read=True)))
    alert = _alert(user)
    session.add(alert)
    session.flush()
    alert.is_read, alert.read_at = True, NOW
    session.flush()


# --- audit logs and deletion rules ---------------------------------------------------------------

def test_audit_log_is_append_only(session):
    log = models.AuditLog(actor_type=AuditActorType.SYSTEM, action="EXPIRY_SWEEP_RUN")
    session.add(log)
    session.flush()
    log.action = "SOMETHING_ELSE"
    with pytest.raises(ImmutableRecordError):
        session.flush()
    session.rollback()
    log = models.AuditLog(actor_type=AuditActorType.SYSTEM, action="EXPIRY_SWEEP_RUN")
    session.add(log)
    session.flush()
    session.delete(log)
    with pytest.raises(ImmutableRecordError):
        session.flush()
    session.rollback()


def test_audit_log_constraints(session):
    rejected(session, "ck_audit_logs_user_actor_has_user",
             lambda: session.add(models.AuditLog(actor_type=AuditActorType.USER, action="LOGIN_SUCCEEDED")))
    rejected(session, "ck_audit_logs_action_format",
             lambda: session.add(models.AuditLog(actor_type=AuditActorType.SYSTEM, action="login succeeded")))


@pytest.mark.parametrize(
    ("table", "constraint"),
    [
        ("users", "fk_beneficiaries_user_id_users"),
        ("beneficiaries", "fk_transactions_beneficiary_id_user_id_beneficiaries"),
        ("transactions", "fk_risk_assessments_transaction_id_transactions"),
    ],
)
def test_history_cannot_be_deleted(session, table, constraint):
    user = add_user(session)
    add_assessment(session, add_transaction(session, user, add_beneficiary(session, user)))
    row_id = {"users": user.id,
              "beneficiaries": session.scalar(select(models.Beneficiary.id)),
              "transactions": session.scalar(select(models.Transaction.id))}[table]
    rejected(session, constraint, lambda: session.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id}))
