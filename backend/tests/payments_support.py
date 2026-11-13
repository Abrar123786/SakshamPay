"""Shared helpers for the P-10 payment tests (PostgreSQL)."""

import uuid
from datetime import datetime, timedelta

from app.models import ApprovalMethod, RiskLevel, TransactionStatus, TransactionType
from app.repositories import BeneficiaryRepository, RiskAssessmentRepository, TransactionRepository, UserRepository
from app.utils.privacy import hash_device_id, protect_upi_id
from tests.pg import TEST_IDENTIFIER_KEY

KEY = TEST_IDENTIFIER_KEY.encode()
PLACEHOLDER_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHRzYWx0$" + "h" * 43
S = TransactionStatus
DEVICE = "device-0001-abcdef"


def make_user(session, *, password_hash=PLACEHOLDER_HASH, last_login_at=None):
    user = UserRepository(session).create(
        full_name="Asha Rao", email=f"pay.{uuid.uuid4().hex[:12]}@example.com", password_hash=password_hash
    )
    if last_login_at is not None:
        user.last_login_at = last_login_at
        session.flush()
    return user


def make_beneficiary(session, user, *, name="Ravi Kumar", created_at=None):
    beneficiary = BeneficiaryRepository(session).create(
        user_id=user.id, beneficiary_name=name, upi=protect_upi_id(f"p{uuid.uuid4().hex[:10]}@okbank", KEY)
    )
    if created_at is not None:
        beneficiary.created_at = created_at
        session.flush()
    return beneficiary


def add_payment(session, user, beneficiary, amount_paise, *, at, status=S.APPROVED, device_id=None):
    """A historical transaction that reached ``status`` through the repository's lifecycle rules."""
    repo = TransactionRepository(session)
    txn = repo.create_idempotent(
        user_id=user.id, beneficiary_id=beneficiary.id, amount_paise=amount_paise, transaction_type=TransactionType.P2P,
        idempotency_key=f"hist-{uuid.uuid4().hex}", request_hash="a" * 64, initiated_at=at,
        device_id_hash=hash_device_id(device_id, KEY) if device_id else None,
    ).transaction
    if status == S.INITIATED:
        return txn
    if status == S.FAILED:
        return repo.transition(txn, S.FAILED, at=at + timedelta(seconds=1))
    analysed = at + timedelta(seconds=1)
    RiskAssessmentRepository(session).create(
        txn, rule_score=0, ml_score=None, risk_level=RiskLevel.MEDIUM, config_version="test", rule_details=[],
        explanation=[], features_snapshot={}, allowed_actions=["CONTINUE", "VERIFY", "CANCEL"], assessed_at=analysed,
    )
    repo.transition(txn, S.ANALYSED, at=analysed)
    if status == S.ANALYSED:
        return txn
    repo.transition(txn, S.AWAITING_USER_ACTION, at=analysed, expires_at=at + timedelta(minutes=10))
    if status == S.APPROVED:
        repo.transition(txn, S.APPROVED, at=at + timedelta(seconds=40), approval_method=ApprovalMethod.CONTINUE)
    elif status == S.CANCELLED:
        repo.transition(txn, S.CANCELLED, at=at + timedelta(seconds=40))
    elif status == S.EXPIRED:
        repo.transition(txn, S.EXPIRED, at=at + timedelta(minutes=10, seconds=5))
    return txn


def ist(year, month, day, hour, minute=0) -> datetime:
    from app.fraud_detection.config import IST

    return datetime(year, month, day, hour, minute, tzinfo=IST)


# ---- API-level helpers (real endpoints, committed data) ---------------------------------------------

import threading  # noqa: E402
from datetime import UTC  # noqa: E402

from argon2 import PasswordHasher  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.fraud_detection.config import IST  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Alert, AuditLog, RiskAssessment, Transaction  # noqa: E402
from tests.conftest import TEST_JWT_SECRET, make_settings  # noqa: E402
from tests.pg import database_for  # noqa: E402

PASSWORD = "correct-horse-battery-staple"
_FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)  # still Argon2id
PASSWORD_HASH = _FAST_HASHER.hash(PASSWORD)
TRANSACTIONS = "/api/v1/transactions"
BENEFICIARIES = "/api/v1/beneficiaries"


def make_app(engine, pg_url, **settings):
    app = create_app(make_settings(DATABASE_URL=pg_url, JWT_SECRET_KEY=TEST_JWT_SECRET, IDENTIFIER_HASH_KEY=TEST_IDENTIFIER_KEY, **settings))
    app.state.database = database_for(engine)
    return app


class Actor:
    """A registered user calling the real API with a valid token."""

    def __init__(self, engine, client):
        self.engine, self.client = engine, client
        with Session(engine, expire_on_commit=False) as session:
            self.user = make_user(session, password_hash=PASSWORD_HASH, last_login_at=datetime.now(UTC) - timedelta(minutes=5))
            session.commit()
        self.id = self.user.id
        self.token = create_access_token(self.id, make_settings(JWT_SECRET_KEY=TEST_JWT_SECRET)).token

    def headers(self, *, key=None, device=DEVICE):
        headers = {"Authorization": f"Bearer {self.token}"}
        if key is not None:
            headers["Idempotency-Key"] = key
        if device is not None:
            headers["X-Device-Id"] = device
        return headers

    def add_beneficiary(self, name="Ravi Kumar", **identifier):
        body = {"beneficiary_name": name, **(identifier or {"upi_id": f"p{uuid.uuid4().hex[:10]}@okbank"})}
        return self.client.post(BENEFICIARIES, json=body, headers=self.headers())

    def beneficiary_id(self, name="Ravi Kumar"):
        response = self.add_beneficiary(name)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def pay(self, beneficiary_id, amount_paise=500_00, *, key=None, device=DEVICE, client=None, **extra):
        body = {"beneficiary_id": str(beneficiary_id), "amount_paise": amount_paise, **extra}
        return (client or self.client).post(TRANSACTIONS, json=body, headers=self.headers(key=key or f"key-{uuid.uuid4().hex}", device=device))

    def get(self, transaction_id):
        return self.client.get(f"{TRANSACTIONS}/{transaction_id}", headers=self.headers(device=None))

    def act(self, transaction_id, action, *, client=None, **body):
        return (client or self.client).post(
            f"{TRANSACTIONS}/{transaction_id}/actions", json={"action": action, **body}, headers=self.headers(device=None)
        )

    def established(self, payments=6, amount_paise=500_00):
        """Give the user an ordinary history: approved payments to one beneficiary from DEVICE at this
        time of day on earlier days. A similar payment now fires no rule, at any time the tests run."""
        beneficiary_id = uuid.UUID(self.beneficiary_id("Usual Payee"))
        now = datetime.now(UTC)
        with Session(self.engine, expire_on_commit=False) as session:
            beneficiary = BeneficiaryRepository(session).get_for_user(beneficiary_id, self.id)
            beneficiary.created_at = now - timedelta(days=60)
            for day in range(1, payments + 1):
                add_payment(session, self.user, beneficiary, amount_paise, at=now - timedelta(days=day, minutes=1), device_id=DEVICE)
            session.commit()
        return str(beneficiary_id)


def night_points(body) -> int:
    """R4 cold-start points for a payment made now: 10 between 00:00 and 05:00 IST, else 0."""
    initiated = datetime.fromisoformat(body["initiated_at"]).astimezone(IST)
    return 10 if initiated.hour < 5 else 0


def db_transaction(engine, transaction_id):
    with Session(engine, expire_on_commit=False) as session:
        return session.get(Transaction, uuid.UUID(str(transaction_id)))


def db_assessments(engine, transaction_id):
    with Session(engine, expire_on_commit=False) as session:
        return list(session.scalars(select(RiskAssessment).where(RiskAssessment.transaction_id == uuid.UUID(str(transaction_id)))))


def audit_trail(engine, transaction_id):
    with Session(engine, expire_on_commit=False) as session:
        return list(session.scalars(select(AuditLog).where(AuditLog.transaction_id == uuid.UUID(str(transaction_id))).order_by(AuditLog.id)))


def audit_actions(engine, transaction_id):
    return [entry.action for entry in audit_trail(engine, transaction_id)]


def alerts_for(engine, transaction_id):
    with Session(engine, expire_on_commit=False) as session:
        return list(session.scalars(select(Alert).where(Alert.transaction_id == uuid.UUID(str(transaction_id))).order_by(Alert.created_at)))


def count_transactions(engine, user_id):
    with Session(engine) as session:
        return session.scalar(text("SELECT count(*) FROM transactions WHERE user_id = :u"), {"u": user_id})


def set_deadline(engine, transaction_id, *, seconds_from_now):
    with Session(engine) as session:
        session.execute(text("UPDATE transactions SET expires_at = :at WHERE id = :id"),
                        {"at": datetime.now(UTC) + timedelta(seconds=seconds_from_now), "id": uuid.UUID(str(transaction_id))})
        session.commit()


def run_together(calls):
    """Start every call at the same moment on its own thread; return results in order."""
    barrier, results = threading.Barrier(len(calls)), [None] * len(calls)

    def run(index, call):
        barrier.wait(timeout=10)
        try:
            results[index] = call()
        except Exception as error:  # noqa: BLE001 - reported to the test
            results[index] = error

    threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


def new_client(app):
    """A separate client for one thread (the app and its connection pool are shared)."""
    return TestClient(app, raise_server_exceptions=False)
