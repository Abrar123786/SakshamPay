"""P-5: repository operations against migrated PostgreSQL.

Covers CRUD for all six repositories, foreign-key and unique constraints,
idempotency (including a real two-connection race), optimistic concurrency,
lifecycle rules, ownership scoping and rollback behaviour.
Runs only with TEST_DATABASE_URL (see tests/pg.py).
"""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.database.session import DbSession
from app.main import create_app
from app.models import (
    AlertSeverity,
    AlertType,
    ApprovalMethod,
    AuditActorType,
    ImmutableRecordError,
    RiskLevel,
    Transaction,
    TransactionStatus,
    TransactionType,
    User,
)
from app.repositories import (
    AlertRepository,
    AuditLogRepository,
    BeneficiaryRepository,
    RiskAssessmentRepository,
    TransactionRepository,
    UserRepository,
)
from app.repositories.base import MAX_PAGE_SIZE
from app.repositories.errors import (
    AlertNotFoundError,
    AssessmentAlreadyExistsError,
    BeneficiaryNotFoundError,
    ConcurrentModificationError,
    DuplicateBeneficiaryError,
    EmailAlreadyRegisteredError,
    IdempotencyKeyReusedError,
    InvalidStateTransitionError,
    PhoneAlreadyRegisteredError,
    TransactionNotFoundError,
)
from app.utils.privacy import protect_account_reference, protect_upi_id
from tests.conftest import make_settings
from tests.pg import TEST_IDENTIFIER_KEY, database_for, require_postgres_url, rollback_session, throwaway_schema

PG_URL = require_postgres_url()
KEY = TEST_IDENTIFIER_KEY.encode()
HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHRzYWx0$" + "h" * 43
S = TransactionStatus


@pytest.fixture(scope="module")
def engine():
    with throwaway_schema(PG_URL) as engine:
        yield engine


@pytest.fixture
def db(engine):
    with rollback_session(engine) as session:
        yield session


# ---- helpers ------------------------------------------------------------------------------------

def make_user(db, email="asha@example.com", **kw) -> User:
    return UserRepository(db).create(full_name="Asha Rao", email=email, password_hash=HASH, **kw)


def make_beneficiary(db, user, account="000123456789", **kw):
    return BeneficiaryRepository(db).create(
        user_id=user.id, beneficiary_name="Ravi Kumar", bank_name="Demo Bank",
        account=protect_account_reference(account, KEY), **kw,
    )


def make_transaction(db, user, beneficiary, key="idem-key-0001", request_hash="a" * 64, **kw) -> Transaction:
    return TransactionRepository(db).create_idempotent(
        user_id=user.id, beneficiary_id=beneficiary.id, amount_paise=250_000,
        transaction_type=TransactionType.P2P, idempotency_key=key, request_hash=request_hash, **kw,
    ).transaction


def make_assessment(db, txn, level=RiskLevel.MEDIUM, allowed=("CONTINUE", "VERIFY", "CANCEL"), rule=35, ml=55):
    return RiskAssessmentRepository(db).create(
        txn, rule_score=rule, ml_score=ml, risk_level=level, config_version="cfg-1",
        model_version="iforest-1" if ml is not None else None,
        ml_details={"percentile": 0.9} if ml is not None else None,
        rule_details=[{"rule": "R2", "points": 25}], explanation=[{"code": "UNUSUAL_AMOUNT"}],
        features_snapshot={"amount_z_user": 2.9}, allowed_actions=list(allowed),
    )


def awaiting(db, txn, level=RiskLevel.MEDIUM, allowed=("CONTINUE", "VERIFY", "CANCEL")):
    repo = TransactionRepository(db)
    make_assessment(db, txn, level, allowed)
    now = datetime.now(UTC)
    repo.transition(txn, S.ANALYSED, at=now)
    repo.transition(txn, S.AWAITING_USER_ACTION, at=now, expires_at=now + timedelta(minutes=10))
    return txn


# ==== users ========================================================================================

def test_user_crud(db):
    repo = UserRepository(db)
    user = repo.create(full_name="  Asha Rao ", email=" Asha.Rao@Example.COM ", password_hash=HASH, phone_number="+919000000001")
    assert user.email == "asha.rao@example.com" and user.full_name == "Asha Rao" and user.is_active
    assert repo.get(user.id) is user
    assert repo.get_by_email("ASHA.RAO@example.com").id == user.id
    repo.update_details(user, full_name="Asha R", phone_number=None)
    assert (user.full_name, user.phone_number) == ("Asha R", None)
    repo.deactivate(user)
    db.expire_all()
    assert repo.get(user.id).is_active is False


def test_duplicate_email_and_phone_become_domain_errors(db):
    make_user(db, email="dup@example.com", phone_number="+919000000002")
    with pytest.raises(EmailAlreadyRegisteredError):
        make_user(db, email="DUP@example.com")
    with pytest.raises(PhoneAlreadyRegisteredError):
        make_user(db, email="other@example.com", phone_number="+919000000002")
    # the failed inserts rolled back only their savepoints; the session is still usable
    assert UserRepository(db).get_by_email("dup@example.com") is not None


def test_plaintext_password_is_never_accepted(db):
    with pytest.raises(IntegrityError, match="ck_users_password_hash_argon2id"):
        UserRepository(db).create(full_name="X", email="x@example.com", password_hash="hunter2")


# ==== beneficiaries ==================================================================================

def test_beneficiary_crud_and_identifier_protection(db):
    user = make_user(db)
    repo = BeneficiaryRepository(db)
    upi = protect_upi_id("Ravi.Kumar@SakshamDemo", KEY)
    beneficiary = repo.create(user_id=user.id, beneficiary_name="Ravi", upi=upi)
    assert beneficiary.upi_id_masked == "ra****@sakshamdemo"
    stored = db.execute(text("SELECT upi_id_masked || coalesce(upi_id_fingerprint, '') FROM beneficiaries WHERE id = :i"),
                        {"i": beneficiary.id}).scalar()
    assert "ravi.kumar" not in stored  # the full UPI ID is not in the database
    assert repo.get_for_user(beneficiary.id, user.id) is beneficiary
    assert repo.find_by_identifier(user.id, upi=protect_upi_id("ravi.kumar@sakshamdemo", KEY)) is beneficiary
    repo.update(beneficiary, beneficiary_name="Ravi K", is_verified=True)
    assert beneficiary.is_verified
    repo.deactivate(beneficiary)
    assert repo.get_for_user(beneficiary.id, user.id) is None
    assert repo.get_for_user(beneficiary.id, user.id, include_inactive=True) is beneficiary
    assert repo.list_for_user(user.id) == []
    repo.reactivate(beneficiary)
    assert repo.list_for_user(user.id) == [beneficiary]


def test_duplicate_beneficiary_for_same_user_is_rejected(db):
    user = make_user(db)
    make_beneficiary(db, user, account="0001 2345 6789")
    with pytest.raises(DuplicateBeneficiaryError):
        make_beneficiary(db, user, account="000123456789")  # same account, different formatting


def test_beneficiaries_are_scoped_to_their_owner(db):
    alice, bob = make_user(db, "alice@example.com"), make_user(db, "bob@example.com")
    bobs = make_beneficiary(db, bob)
    repo = BeneficiaryRepository(db)
    assert repo.get_for_user(bobs.id, alice.id) is None
    with pytest.raises(BeneficiaryNotFoundError):
        repo.require_for_user(bobs.id, alice.id)


# ==== transactions ======================================================================================

def test_transaction_create_and_reads(db):
    user = make_user(db)
    beneficiary = make_beneficiary(db, user)
    repo = TransactionRepository(db)
    result = repo.create_idempotent(user_id=user.id, beneficiary_id=beneficiary.id, amount_paise=4_800_000,
                                    transaction_type=TransactionType.P2P, idempotency_key="key-00000001",
                                    request_hash="c" * 64, description="Rent")
    txn = result.transaction
    assert result.created and txn.status == S.INITIATED and txn.version == 1 and txn.currency == "INR"
    assert repo.get_for_user(txn.id, user.id) is txn
    assert repo.get_by_idempotency_key(user.id, "key-00000001") is txn
    assert repo.list_for_user(user.id) == [txn]
    assert repo.list_for_user(user.id, statuses=[S.APPROVED]) == []
    assert txn in repo.list_by_status(S.INITIATED)


def test_idempotent_replay_and_key_reuse(db):
    user = make_user(db)
    beneficiary = make_beneficiary(db, user)
    first = make_transaction(db, user, beneficiary, key="same-key-001", request_hash="d" * 64)
    replay = TransactionRepository(db).create_idempotent(
        user_id=user.id, beneficiary_id=beneficiary.id, amount_paise=250_000, transaction_type=TransactionType.P2P,
        idempotency_key="same-key-001", request_hash="d" * 64,
    )
    assert replay.created is False and replay.transaction.id == first.id
    with pytest.raises(IdempotencyKeyReusedError):
        make_transaction(db, user, beneficiary, key="same-key-001", request_hash="e" * 64)
    assert db.scalar(select(Transaction.id).where(Transaction.idempotency_key == "same-key-001").limit(2)) == first.id


def test_cannot_create_transaction_for_another_users_beneficiary(db):
    alice, bob = make_user(db, "alice@example.com"), make_user(db, "bob@example.com")
    with pytest.raises(BeneficiaryNotFoundError):
        make_transaction(db, alice, make_beneficiary(db, bob))


def test_transactions_are_scoped_to_their_owner(db):
    alice, bob = make_user(db, "alice@example.com"), make_user(db, "bob@example.com")
    txn = make_transaction(db, bob, make_beneficiary(db, bob))
    repo = TransactionRepository(db)
    assert repo.get_for_user(txn.id, alice.id) is None
    assert repo.list_for_user(alice.id) == []
    with pytest.raises(TransactionNotFoundError):
        repo.get_for_update(txn.id, alice.id)


def test_full_lifecycle_via_repository(db):
    user = make_user(db)
    txn = make_transaction(db, user, make_beneficiary(db, user))
    repo = TransactionRepository(db)
    awaiting(db, txn)
    assert txn.analysed_at and txn.expires_at and txn.status == S.AWAITING_USER_ACTION
    assert repo.record_failed_verification(txn) == 1
    repo.transition(txn, S.APPROVED, approval_method=ApprovalMethod.VERIFIED)
    assert txn.completed_at and txn.approval_method == ApprovalMethod.VERIFIED and txn.version == 5


@pytest.mark.parametrize(
    ("setup", "target", "kwargs", "message"),
    [
        ("initiated", S.APPROVED, {"approval_method": ApprovalMethod.CONTINUE}, "from INITIATED to APPROVED"),
        ("initiated", S.ANALYSED, {}, "after its risk assessment"),
        ("analysed", S.AWAITING_USER_ACTION, {}, "expiry time in the future"),
        ("awaiting", S.APPROVED, {}, "needs an approval method"),
        ("awaiting_high", S.APPROVED, {"approval_method": ApprovalMethod.CONTINUE}, "does not allow approval by CONTINUE"),
        ("awaiting", S.CANCELLED, {"approval_method": ApprovalMethod.CONTINUE}, "Only APPROVED"),
        ("cancelled", S.APPROVED, {"approval_method": ApprovalMethod.CONTINUE}, "from CANCELLED"),
    ],
)
def test_lifecycle_rules_are_enforced(db, setup, target, kwargs, message):
    user = make_user(db)
    txn = make_transaction(db, user, make_beneficiary(db, user))
    repo = TransactionRepository(db)
    if setup == "analysed":
        make_assessment(db, txn)
        repo.transition(txn, S.ANALYSED)
    elif setup.startswith("awaiting"):
        high = setup == "awaiting_high"
        awaiting(db, txn, RiskLevel.HIGH if high else RiskLevel.MEDIUM,
                 ("VERIFY", "CANCEL") if high else ("CONTINUE", "VERIFY", "CANCEL"))
    elif setup == "cancelled":
        awaiting(db, txn)
        repo.transition(txn, S.CANCELLED)
    with pytest.raises(InvalidStateTransitionError, match=message):
        repo.transition(txn, target, **kwargs)


def test_verification_attempts_are_capped(db):
    user = make_user(db)
    txn = awaiting(db, make_transaction(db, user, make_beneficiary(db, user)))
    repo = TransactionRepository(db)
    assert [repo.record_failed_verification(txn) for _ in range(3)] == [1, 2, 3]
    with pytest.raises(InvalidStateTransitionError, match="No verification attempts"):
        repo.record_failed_verification(txn)


def test_sweep_queries(db):
    user = make_user(db)
    beneficiary = make_beneficiary(db, user)
    repo = TransactionRepository(db)
    old = make_transaction(db, user, beneficiary, key="stale-key-01", initiated_at=datetime.now(UTC) - timedelta(hours=1))
    assert old in repo.list_stale_initiated(datetime.now(UTC) - timedelta(minutes=2))
    past = datetime.now(UTC) - timedelta(minutes=30)
    txn = make_transaction(db, user, beneficiary, key="expiring-key-1", initiated_at=past - timedelta(seconds=5))
    make_assessment(db, txn)
    repo.transition(txn, S.ANALYSED, at=past)
    repo.transition(txn, S.AWAITING_USER_ACTION, at=past, expires_at=past + timedelta(minutes=10))
    assert txn in repo.list_expired_awaiting(datetime.now(UTC))


def test_list_limits_are_clamped(db):
    user = make_user(db)
    beneficiary = make_beneficiary(db, user)
    for i in range(3):
        make_transaction(db, user, beneficiary, key=f"page-key-{i:04}")
    repo = TransactionRepository(db)
    assert len(repo.list_for_user(user.id, limit=2)) == 2
    assert len(repo.list_for_user(user.id, limit=2, offset=2)) == 1
    assert len(repo.list_for_user(user.id, limit=10_000)) == 3  # clamped to MAX_PAGE_SIZE, not an error
    assert MAX_PAGE_SIZE == 100


# ==== risk assessments ===================================================================================

def test_assessment_create_and_reads(db):
    user = make_user(db)
    txn = make_transaction(db, user, make_beneficiary(db, user))
    assessment = make_assessment(db, txn, rule=70, ml=82, level=RiskLevel.HIGH)
    assert assessment.final_risk_score == 75  # computed by the repository with the approved formula
    repo = RiskAssessmentRepository(db)
    assert repo.get_by_transaction(txn.id) is assessment
    assert repo.get_by_transaction(txn.id, user_id=user.id) is assessment
    other = make_user(db, "other@example.com")
    assert repo.get_by_transaction(txn.id, user_id=other.id) is None
    assert repo.list_for_user(user.id) == [assessment]
    assert repo.list_for_user(user.id, risk_level=RiskLevel.LOW) == []


def test_rules_only_assessment(db):
    user = make_user(db)
    txn = make_transaction(db, user, make_beneficiary(db, user))
    assessment = make_assessment(db, txn, rule=40, ml=None)
    assert assessment.final_risk_score == 40 and assessment.ml_details is None


def test_one_assessment_per_transaction_and_only_while_initiated(db):
    user = make_user(db)
    txn = make_transaction(db, user, make_beneficiary(db, user))
    make_assessment(db, txn)
    with pytest.raises(AssessmentAlreadyExistsError):
        make_assessment(db, txn)
    TransactionRepository(db).transition(txn, S.ANALYSED)
    with pytest.raises(InvalidStateTransitionError, match="Only an INITIATED"):
        make_assessment(db, txn)


def test_assessments_cannot_be_changed_through_the_orm(db):
    user = make_user(db)
    assessment = make_assessment(db, make_transaction(db, user, make_beneficiary(db, user)))
    assessment.rule_score = 0
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()


# ==== alerts =====================================================================================================

def test_alert_create_list_and_read_state(db):
    user = make_user(db)
    txn = make_transaction(db, user, make_beneficiary(db, user))
    assessment = make_assessment(db, txn)
    repo = AlertRepository(db)
    first = repo.create(user_id=user.id, alert_type=AlertType.RISK_WARNING, severity=AlertSeverity.WARNING,
                        title="Medium-risk payment", message="Unusual amount.", transaction_id=txn.id,
                        risk_assessment_id=assessment.id)
    second = repo.create(user_id=user.id, alert_type=AlertType.SECURITY_NOTICE, severity=AlertSeverity.INFO,
                         title="New device", message="A new device was used.")
    assert repo.count_unread(user.id) == 2
    assert set(repo.list_unread(user.id)) == {first, second}
    read = repo.mark_read(first.id, user.id)
    read_at = read.read_at
    assert read.is_read and read_at is not None
    assert repo.mark_read(first.id, user.id).read_at == read_at  # idempotent
    assert repo.list_unread(user.id) == [second]
    assert repo.mark_all_read(user.id) == 1
    assert repo.count_unread(user.id) == 0
    assert len(repo.list_for_user(user.id)) == 2


def test_alerts_are_scoped_and_links_must_match(db):
    alice, bob = make_user(db, "alice@example.com"), make_user(db, "bob@example.com")
    bobs_txn = make_transaction(db, bob, make_beneficiary(db, bob))
    repo = AlertRepository(db)
    with pytest.raises(TransactionNotFoundError):  # alert for Alice about Bob's transaction
        repo.create(user_id=alice.id, alert_type=AlertType.RISK_WARNING, severity=AlertSeverity.INFO,
                    title="x", message="y", transaction_id=bobs_txn.id)
    bobs_alert = repo.create(user_id=bob.id, alert_type=AlertType.SECURITY_NOTICE, severity=AlertSeverity.INFO,
                             title="x", message="y")
    with pytest.raises(AlertNotFoundError):
        repo.mark_read(bobs_alert.id, alice.id)


# ==== audit logs =================================================================================================

def test_audit_record_and_filters(db):
    user = make_user(db)
    txn = make_transaction(db, user, make_beneficiary(db, user))
    repo = AuditLogRepository(db)
    token = request_id_var.set("req-audit-0001")
    try:
        first = repo.record(action="TRANSACTION_INITIATED", actor_type=AuditActorType.USER, user_id=user.id,
                            transaction_id=txn.id, new_values={"status": "INITIATED"},
                            ip_address="203.0.113.57", user_agent="Mozilla/5.0")
    finally:
        request_id_var.reset(token)
    second = repo.record(action="TRANSACTION_CANCELLED", actor_type=AuditActorType.USER, user_id=user.id,
                         transaction_id=txn.id)
    system = repo.record(action="EXPIRY_SWEEP_RUN", actor_type=AuditActorType.SYSTEM, metadata={"expired": 0})
    db.expire_all()
    assert first.request_id == "req-audit-0001"
    assert str(first.ip_address) == "203.0.113.0/24"  # truncated before storage
    assert {e.id for e in repo.find(user_id=user.id)} == {first.id, second.id}
    assert [e.id for e in repo.find(transaction_id=txn.id, action="TRANSACTION_CANCELLED")] == [second.id]
    assert system.id in {e.id for e in repo.find(action="EXPIRY_SWEEP_RUN")}
    assert [e.id for e in repo.history_for_transaction(txn.id)] == [first.id, second.id]
    assert repo.find(since=datetime.now(UTC) + timedelta(days=1)) == []


def test_audit_entries_cannot_be_changed_or_deleted_through_the_orm(db):
    entry = AuditLogRepository(db).record(action="PROBE_EVENT", actor_type=AuditActorType.SYSTEM)
    db.delete(entry)
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()


# ==== rollback behaviour =====================================================================================

def test_rollback_discards_uncommitted_work(db):
    make_user(db, "kept@example.com")
    db.commit()  # savepoint released (the outer test transaction still rolls everything back later)
    make_user(db, "discarded@example.com")
    db.rollback()
    repo = UserRepository(db)
    assert repo.get_by_email("kept@example.com") is not None
    assert repo.get_by_email("discarded@example.com") is None


def test_failed_write_keeps_earlier_work_in_the_same_transaction(db):
    user = make_user(db)
    make_beneficiary(db, user)
    with pytest.raises(DuplicateBeneficiaryError):
        make_beneficiary(db, user)
    make_transaction(db, user, BeneficiaryRepository(db).list_for_user(user.id)[0])  # session still usable
    assert len(TransactionRepository(db).list_for_user(user.id)) == 1


def test_request_failure_rolls_back_through_the_p3_session_dependency(engine):
    app = create_app(make_settings(DATABASE_URL=PG_URL))
    app.state.database = database_for(engine)

    @app.post("/_test/create-then-fail")
    def create_then_fail(session: DbSession):
        UserRepository(session).create(full_name="Ghost", email="ghost@example.com", password_hash=HASH)
        raise RuntimeError("boom after the insert")

    @app.post("/_test/create-and-commit")
    def create_and_commit(session: DbSession):
        UserRepository(session).create(full_name="Real", email="committed@example.com", password_hash=HASH)
        session.commit()
        return {"ok": True}

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            assert client.post("/_test/create-then-fail").status_code == 500
            assert client.post("/_test/create-and-commit").status_code == 200
        with Session(engine) as check:
            repo = UserRepository(check)
            assert repo.get_by_email("ghost@example.com") is None
            assert repo.get_by_email("committed@example.com") is not None
    finally:
        with engine.begin() as connection:  # remove the committed user (no history references it)
            connection.execute(text("DELETE FROM users WHERE email = 'committed@example.com'"))


# ==== concurrency (real commits, separate connections) ===========================================================

@pytest.fixture
def committed_engine():
    with throwaway_schema(PG_URL) as engine:
        yield engine


def _seed_owner(engine):
    with Session(engine, expire_on_commit=False) as session:
        user = make_user(session)
        beneficiary = make_beneficiary(session, user)
        session.commit()
        return user.id, beneficiary.id


def test_optimistic_concurrency_detects_lost_update(committed_engine):
    user_id, beneficiary_id = _seed_owner(committed_engine)
    with Session(committed_engine) as setup:
        txn = TransactionRepository(setup).create_idempotent(
            user_id=user_id, beneficiary_id=beneficiary_id, amount_paise=100, transaction_type=TransactionType.P2P,
            idempotency_key="race-key-0001", request_hash="f" * 64).transaction
        awaiting(setup, txn)
        setup.commit()
        txn_id = txn.id

    with Session(committed_engine) as first, Session(committed_engine) as second:
        mine = TransactionRepository(first).require_for_user(txn_id, user_id)
        theirs = TransactionRepository(second).require_for_user(txn_id, user_id)
        TransactionRepository(second).transition(theirs, S.CANCELLED)
        second.commit()
        with pytest.raises(ConcurrentModificationError):
            TransactionRepository(first).transition(mine, S.APPROVED, approval_method=ApprovalMethod.CONTINUE)
        first.rollback()

    with Session(committed_engine) as check:
        assert check.get(Transaction, txn_id).status == S.CANCELLED  # the later writer did not overwrite


def test_row_lock_blocks_a_concurrent_writer(committed_engine):
    user_id, beneficiary_id = _seed_owner(committed_engine)
    with Session(committed_engine) as setup:
        txn_id = TransactionRepository(setup).create_idempotent(
            user_id=user_id, beneficiary_id=beneficiary_id, amount_paise=100, transaction_type=TransactionType.P2P,
            idempotency_key="lock-key-0001", request_hash="f" * 64).transaction.id
        setup.commit()
    with Session(committed_engine) as holder, Session(committed_engine) as waiter:
        TransactionRepository(holder).get_for_update(txn_id, user_id)
        waiter.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(OperationalError, match="lock timeout"):
            TransactionRepository(waiter).get_for_update(txn_id, user_id)
        holder.rollback()


def test_concurrent_requests_with_same_idempotency_key_create_one_transaction(committed_engine):
    user_id, beneficiary_id = _seed_owner(committed_engine)
    arguments = dict(user_id=user_id, beneficiary_id=beneficiary_id, amount_paise=500, transaction_type=TransactionType.P2P,
                     idempotency_key="double-click-01", request_hash="9" * 64)
    results = {}

    first = Session(committed_engine)
    results["first"] = TransactionRepository(first).create_idempotent(**arguments)  # inserted, not yet committed

    def second_request():
        with Session(committed_engine) as second:
            # blocks on the unique index until the first request commits, then replays it
            result = TransactionRepository(second).create_idempotent(**arguments)
            results["second"] = (result.created, result.transaction.id)
            second.commit()

    worker = threading.Thread(target=second_request)
    worker.start()
    worker.join(timeout=0.5)
    assert worker.is_alive()  # really waiting on the first request's uncommitted row
    first_id = results["first"].transaction.id
    first.commit()
    first.close()
    worker.join(timeout=10)

    assert results["first"].created is True
    assert results["second"] == (False, first_id)  # replayed the first request's transaction
    with Session(committed_engine) as check:
        count = check.scalar(text("SELECT count(*) FROM transactions WHERE idempotency_key = 'double-click-01'"))
        assert count == 1
