"""P-9: GET /api/v1/dashboard/summary against migrated PostgreSQL.

Runs only with TEST_DATABASE_URL (see tests/pg.py). Data is committed in one
throwaway schema; every test creates its own users, so tests are independent.

Covers: authentication, user isolation, exact aggregates, the 30-day boundary,
every status key, a user with no transactions, a payment past its deadline that
the sweep has not yet expired, unread-alert semantics, read-only behaviour,
Cache-Control and the development seed.
"""

import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.exc import InternalError
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.database.session import get_read_only_db
from app.main import create_app
from app.models import Alert, AlertSeverity, AlertType, ApprovalMethod, RiskLevel, Transaction, TransactionStatus, TransactionType
from app.repositories import AlertRepository, BeneficiaryRepository, RiskAssessmentRepository, TransactionRepository, UserRepository
from app.services import dashboard as dashboard_service
from app.services.dashboard import DashboardService, NotReadOnlySessionError
from app.utils.privacy import protect_account_reference
from tests.conftest import TEST_JWT_SECRET, make_settings
from tests.pg import TEST_IDENTIFIER_KEY, database_for, require_postgres_url, settings_for, throwaway_schema

PG_URL = require_postgres_url()
SUMMARY = "/api/v1/dashboard/summary"
HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHRzYWx0$" + "h" * 43
KEY = TEST_IDENTIFIER_KEY.encode()
S = TransactionStatus
ALL_STATUSES = [s.value for s in TransactionStatus]


@pytest.fixture(scope="module")
def engine():
    with throwaway_schema(PG_URL) as engine:
        yield engine


@pytest.fixture
def client(engine):
    app = create_app(make_settings(DATABASE_URL=PG_URL, JWT_SECRET_KEY=TEST_JWT_SECRET))
    app.state.database = database_for(engine)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


# ---- data helpers (committed) -----------------------------------------------------------------------

class World:
    """Builds committed data for one user: beneficiary, transactions in any state, alerts."""

    def __init__(self, engine):
        self.engine = engine
        with Session(engine, expire_on_commit=False) as session:
            self.user = UserRepository(session).create(
                full_name="Test User", email=f"dash.{uuid.uuid4().hex[:12]}@example.com", password_hash=HASH
            )
            self.beneficiary = BeneficiaryRepository(session).create(
                user_id=self.user.id,
                beneficiary_name="Ravi Kumar",
                account=protect_account_reference(str(uuid.uuid4().int)[:12], KEY),
            )
            session.commit()

    def token(self):
        return create_access_token(self.user.id, make_settings(JWT_SECRET_KEY=TEST_JWT_SECRET)).token

    def headers(self):
        return {"Authorization": f"Bearer {self.token()}"}

    def transaction(self, status, amount_paise=100_00, *, created_at=None, expires_in=timedelta(minutes=10)):
        """A transaction that reached `status` through the real lifecycle rules.

        A negative `expires_in` simulates time passing: the payment is created with a
        future deadline (the repository requires one) and the deadline is then moved
        into the past, as if the user never acted and the sweep has not run yet.
        """
        with Session(self.engine, expire_on_commit=False) as session:
            repo = TransactionRepository(session)
            txn = repo.create_idempotent(
                user_id=self.user.id, beneficiary_id=self.beneficiary.id, amount_paise=amount_paise,
                transaction_type=TransactionType.P2P, idempotency_key=f"dash-{uuid.uuid4().hex}", request_hash="a" * 64,
            ).transaction
            now = datetime.now(UTC)  # after the insert, so lifecycle timestamps follow initiated_at
            if status == S.FAILED:
                repo.transition(txn, S.FAILED, at=now)
            elif status != S.INITIATED:
                RiskAssessmentRepository(session).create(
                    txn, rule_score=10, ml_score=None, risk_level=RiskLevel.LOW, config_version="test",
                    rule_details=[], explanation=[], features_snapshot={}, allowed_actions=["CONTINUE", "CANCEL"],
                )
                repo.transition(txn, S.ANALYSED, at=now)
                if status != S.ANALYSED:
                    repo.transition(txn, S.AWAITING_USER_ACTION, at=now, expires_at=now + max(expires_in, timedelta(minutes=10)))
                    if status == S.APPROVED:
                        repo.transition(txn, S.APPROVED, at=now, approval_method=ApprovalMethod.CONTINUE)
                    elif status in (S.CANCELLED, S.EXPIRED):
                        repo.transition(txn, status, at=now)
            if status == S.AWAITING_USER_ACTION and expires_in <= timedelta(0):
                session.execute(text("UPDATE transactions SET expires_at = :at WHERE id = :id"), {"at": now + expires_in, "id": txn.id})
            if created_at is not None:
                session.execute(text("UPDATE transactions SET created_at = :at WHERE id = :id"), {"at": created_at, "id": txn.id})
            session.commit()
            return txn

    def alert(self, *, read=False, created_at=None):
        with Session(self.engine, expire_on_commit=False) as session:
            repo = AlertRepository(session)
            alert = repo.create(
                user_id=self.user.id, alert_type=AlertType.SECURITY_NOTICE, severity=AlertSeverity.INFO,
                title="Notice", message="Test alert",
            )
            if read:
                repo.mark_read(alert.id, self.user.id)
            if created_at is not None:
                session.execute(text("UPDATE alerts SET created_at = :at WHERE id = :id"), {"at": created_at, "id": alert.id})
            session.commit()
            return alert

    def summary(self, now=None):
        """Call the service directly (fixed `now` for boundary tests), on the real read-only session."""
        with read_only_session(self.engine) as session:
            return DashboardService(session).summary(self.user.id, now=now).model_dump(mode="json")


@contextmanager
def read_only_session(engine):
    """The session the endpoint gets: driven through the real get_read_only_db dependency."""
    dependency = get_read_only_db(database_for(engine))
    session = next(dependency)
    try:
        yield session
    finally:
        dependency.close()  # runs the dependency's cleanup (session.close)


@pytest.fixture
def world(engine):
    return World(engine)


# ---- authentication ------------------------------------------------------------------------------

def test_requires_authentication(client):
    response = client.get(SUMMARY)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_deactivated_user_is_rejected(client, engine, world):
    with Session(engine) as session:
        repo = UserRepository(session)
        repo.deactivate(repo.get(world.user.id))
        session.commit()
    response = client.get(SUMMARY, headers=world.headers())
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_token_for_unknown_user_is_rejected(client):
    token = create_access_token(uuid.uuid4(), make_settings(JWT_SECRET_KEY=TEST_JWT_SECRET)).token
    response = client.get(SUMMARY, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


# ---- zero-transaction user ---------------------------------------------------------------------------

def test_new_user_gets_zeros_and_every_status_key(client, world):
    response = client.get(SUMMARY, headers=world.headers())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["transactions"] == {
        "total": 0,
        "by_status": dict.fromkeys(ALL_STATUSES, 0),
        "awaiting_action": 0,
        "approved_amount_paise": 0,
    }
    assert body["alerts"] == {"unread": 0}
    assert body["period"]["days"] == 30
    start = datetime.fromisoformat(body["period"]["start"])
    end = datetime.fromisoformat(body["period"]["end"])
    assert end - start == timedelta(days=30)
    assert abs((end - datetime.now(UTC)).total_seconds()) < 60


# ---- aggregates -----------------------------------------------------------------------------------------

def test_exact_aggregates_across_every_status(client, world):
    world.transaction(S.INITIATED, 1_00)
    world.transaction(S.ANALYSED, 2_00)
    world.transaction(S.AWAITING_USER_ACTION, 4_00)
    world.transaction(S.APPROVED, 1_234_56)
    world.transaction(S.APPROVED, 50_000_00)
    world.transaction(S.CANCELLED, 8_00)
    world.transaction(S.EXPIRED, 16_00)
    world.transaction(S.FAILED, 32_00)

    body = client.get(SUMMARY, headers=world.headers()).json()["transactions"]
    assert body["by_status"] == {
        "INITIATED": 1, "ANALYSED": 1, "AWAITING_USER_ACTION": 1, "APPROVED": 2,
        "CANCELLED": 1, "EXPIRED": 1, "FAILED": 1,
    }
    assert body["total"] == 8 == sum(body["by_status"].values())
    assert body["approved_amount_paise"] == 1_234_56 + 50_000_00  # only APPROVED amounts
    assert body["awaiting_action"] == 1


def test_large_amounts_stay_exact_integers(world):
    world.transaction(S.APPROVED, 9_000_000_000_00)  # ₹90 crore (simulated)
    world.transaction(S.APPROVED, 1)
    assert world.summary()["transactions"]["approved_amount_paise"] == 9_000_000_000_01


# ---- user isolation ------------------------------------------------------------------------------------

def test_users_only_ever_see_their_own_data(client, engine):
    asha, ravi = World(engine), World(engine)
    asha.transaction(S.APPROVED, 500_00)
    asha.alert()
    ravi.transaction(S.APPROVED, 999_00)
    ravi.transaction(S.CANCELLED, 1_00)
    ravi.alert()
    ravi.alert()

    a = client.get(SUMMARY, headers=asha.headers()).json()
    r = client.get(SUMMARY, headers=ravi.headers()).json()
    assert (a["transactions"]["total"], a["transactions"]["approved_amount_paise"], a["alerts"]["unread"]) == (1, 500_00, 1)
    assert (r["transactions"]["total"], r["transactions"]["approved_amount_paise"], r["alerts"]["unread"]) == (2, 999_00, 2)


def test_query_parameters_cannot_select_another_user(client, engine):
    asha, ravi = World(engine), World(engine)
    ravi.transaction(S.APPROVED, 999_00)
    response = client.get(SUMMARY, params={"user_id": str(ravi.user.id)}, headers=asha.headers())
    assert response.json()["transactions"]["total"] == 0


# ---- 30-day window (created_at) ----------------------------------------------------------------------

def test_window_boundaries(world):
    now = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1)
    world.transaction(S.APPROVED, 1_00, created_at=now - timedelta(days=30))  # exactly at start: in
    world.transaction(S.APPROVED, 2_00, created_at=now - timedelta(days=30, microseconds=1))  # just before: out
    world.transaction(S.APPROVED, 4_00, created_at=now - timedelta(days=45))  # long ago: out
    world.transaction(S.APPROVED, 8_00, created_at=now)  # exactly at end: in
    world.transaction(S.APPROVED, 16_00, created_at=now + timedelta(seconds=1))  # after end: out

    body = world.summary(now=now)
    assert body["period"] == {"days": 30, "start": (now - timedelta(days=30)).isoformat().replace("+00:00", "Z"), "end": now.isoformat().replace("+00:00", "Z")}
    assert body["transactions"]["by_status"]["APPROVED"] == 2
    assert body["transactions"]["total"] == 2
    assert body["transactions"]["approved_amount_paise"] == 1_00 + 8_00


def test_window_applies_to_every_figure_except_unread_alerts(world):
    now = datetime.now(UTC)
    old = now - timedelta(days=60)
    world.transaction(S.AWAITING_USER_ACTION, created_at=old, expires_in=timedelta(days=365))
    world.transaction(S.APPROVED, 7_00, created_at=old)
    world.alert(created_at=old)
    body = world.summary(now=now)
    assert body["transactions"]["total"] == 0
    assert body["transactions"]["awaiting_action"] == 0
    assert body["transactions"]["approved_amount_paise"] == 0
    assert body["alerts"]["unread"] == 1  # unread alerts are counted at any age


# ---- awaiting action and the expiry sweep ------------------------------------------------------------

def test_payment_past_its_deadline_is_not_awaiting_action(world):
    live = world.transaction(S.AWAITING_USER_ACTION, expires_in=timedelta(minutes=10))
    stale = world.transaction(S.AWAITING_USER_ACTION, expires_in=timedelta(minutes=-1))  # sweep has not run yet

    body = world.summary()["transactions"]
    # Stored state is reported as stored...
    assert body["by_status"]["AWAITING_USER_ACTION"] == 2
    assert body["by_status"]["EXPIRED"] == 0
    # ...but only the one the user can still act on needs their action.
    assert body["awaiting_action"] == 1
    assert live.id != stale.id


def test_deadline_boundary_matches_the_expiry_sweep(world, engine):
    txn = world.transaction(S.AWAITING_USER_ACTION)
    with Session(engine) as session:
        expires_at = session.get(Transaction, txn.id).expires_at
        # The sweep expires rows with expires_at < now; the dashboard counts expires_at >= now.
        assert txn.id not in [t.id for t in TransactionRepository(session).list_expired_awaiting(expires_at)]
        assert txn.id in [t.id for t in TransactionRepository(session).list_expired_awaiting(expires_at + timedelta(microseconds=1))]
    assert world.summary(now=expires_at)["transactions"]["awaiting_action"] == 1
    assert world.summary(now=expires_at + timedelta(microseconds=1))["transactions"]["awaiting_action"] == 0


# ---- unread alerts -----------------------------------------------------------------------------------

def test_unread_alerts_count(client, world):
    world.alert()
    world.alert()
    world.alert(read=True)
    world.alert(created_at=datetime.now(UTC) - timedelta(days=400))
    assert client.get(SUMMARY, headers=world.headers()).json()["alerts"] == {"unread": 3}


# ---- read-only ------------------------------------------------------------------------------------------

def snapshot(engine, user_id):
    with Session(engine) as session:
        txns = session.execute(
            select(Transaction.id, Transaction.status, Transaction.version, Transaction.updated_at, Transaction.expires_at)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.id)
        ).all()
        alerts = session.execute(select(Alert.id, Alert.is_read, Alert.read_at).where(Alert.user_id == user_id).order_by(Alert.id)).all()
        audit = session.scalar(text("SELECT count(*) FROM audit_logs WHERE user_id = :u"), {"u": user_id})
        return txns, alerts, audit


def test_reading_the_summary_changes_nothing(client, engine, world):
    world.transaction(S.AWAITING_USER_ACTION, expires_in=timedelta(minutes=-5))  # would be expired by a sweep
    world.transaction(S.APPROVED)
    world.alert()
    before = snapshot(engine, world.user.id)
    for _ in range(3):
        assert client.get(SUMMARY, headers=world.headers()).status_code == 200
    assert snapshot(engine, world.user.id) == before


def test_read_only_session_starts_read_only_and_repeatable_read(engine, world):
    with read_only_session(engine) as session:
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        assert session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        DashboardService(session).summary(world.user.id)
        with pytest.raises(InternalError, match="read-only transaction"):
            session.execute(text("UPDATE transactions SET description = 'x' WHERE user_id = :u"), {"u": world.user.id})


def test_read_only_session_sees_one_snapshot(engine, world):
    """REPEATABLE READ: figures within one request cannot disagree because of a concurrent write."""
    with read_only_session(engine) as session:
        first = DashboardService(session).summary(world.user.id)
        world.transaction(S.APPROVED, 123_00)  # committed by another session meanwhile
        second = DashboardService(session).summary(world.user.id)
        assert second.transactions == first.transactions
    assert world.summary()["transactions"]["approved_amount_paise"] == 123_00  # a new request sees it


def test_service_refuses_a_read_write_session(engine, world):
    with Session(engine) as session, pytest.raises(NotReadOnlySessionError):
        DashboardService(session).summary(world.user.id)


def test_service_never_commits(monkeypatch, engine, world):
    def forbidden(self):
        raise AssertionError("the dashboard must not commit")

    monkeypatch.setattr(Session, "commit", forbidden)
    with read_only_session(engine) as session:
        DashboardService(session).summary(world.user.id)


# ---- the real endpoint: session lifecycle -----------------------------------------------------------------

@pytest.fixture
def statements(engine):
    """Every SQL statement run through the engine, with the DB-API connection it ran on."""
    seen = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append((id(conn.connection.dbapi_connection), " ".join(statement.split())))

    event.listen(engine, "before_cursor_execute", record)
    yield seen
    event.remove(engine, "before_cursor_execute", record)


def open_in_transaction(engine):
    """Server-side sessions of this database left idle inside a transaction."""
    with engine.connect() as connection:
        return connection.scalar(text(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
            "AND state LIKE 'idle in transaction%' AND pid <> pg_backend_pid()"
        ))


def assert_no_leaks(engine, baseline):
    deadline = time.monotonic() + 3
    while engine.pool.checkedout() != baseline and time.monotonic() < deadline:
        time.sleep(0.02)
    assert engine.pool.checkedout() == baseline, "a pooled connection was not returned"
    assert open_in_transaction(engine) == 0, "a connection was left idle in a transaction"


def test_authenticated_request_auth_first_then_a_separate_read_only_transaction(client, engine, world, statements):
    world.transaction(S.APPROVED, 250_00)
    world.alert()
    statements.clear()  # only this request's statements (pooled connections are reused)
    response = client.get(SUMMARY, headers=world.headers())

    assert response.status_code == 200
    assert response.json()["transactions"]["approved_amount_paise"] == 250_00
    assert response.json()["alerts"]["unread"] == 1

    auth = [i for i, (_, sql) in enumerate(statements) if sql.startswith("SELECT") and "FROM users" in sql]
    setup = [i for i, (_, sql) in enumerate(statements) if sql.startswith("SET TRANSACTION")]
    assert len(auth) == 1 and len(setup) == 1
    auth_conn, dash_conn = statements[auth[0]][0], statements[setup[0]][0]

    # 1. The user is loaded first, on the authentication session (CurrentUser, unchanged).
    assert auth[0] < setup[0]
    # 2. The dashboard runs on a different connection...
    assert dash_conn != auth_conn
    on_dashboard = [sql for conn, sql in statements if conn == dash_conn]
    # 3. ...whose first statement sets the transaction characteristics,
    assert on_dashboard[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    # 4. ...and which runs every aggregate query.
    assert any("FROM transactions" in sql for sql in on_dashboard)
    assert any("FROM alerts" in sql for sql in on_dashboard)
    assert not any("FROM transactions" in sql or "FROM alerts" in sql for conn, sql in statements if conn == auth_conn)


def test_write_inside_the_dashboard_transaction_is_rejected_by_postgres(client, engine, world, monkeypatch):
    txn = world.transaction(S.APPROVED, 250_00)
    original = DashboardService.summary
    observed = {}

    def summary_attempting_a_write(self, user_id, *, now=None):
        observed["read_only"] = self.session.scalar(text("SHOW transaction_read_only"))
        observed["isolation"] = self.session.scalar(text("SHOW transaction_isolation"))
        try:
            with self.session.begin_nested():  # savepoint, so the request can continue afterwards
                self.session.execute(text("UPDATE transactions SET description = 'tampered' WHERE id = :id"), {"id": txn.id})
        except InternalError as error:
            observed["error"] = str(error.orig)
        return original(self, user_id, now=now)

    monkeypatch.setattr(dashboard_service.DashboardService, "summary", summary_attempting_a_write)
    response = client.get(SUMMARY, headers=world.headers())

    assert response.status_code == 200
    assert observed["read_only"] == "on" and observed["isolation"] == "repeatable read"
    assert "cannot execute UPDATE in a read-only transaction" in observed["error"]
    with Session(engine) as session:
        assert session.get(Transaction, txn.id).description is None


def test_repeated_requests_change_nothing_and_leak_no_connections(client, engine, world):
    world.transaction(S.AWAITING_USER_ACTION, expires_in=timedelta(minutes=-5))
    world.transaction(S.APPROVED)
    world.alert()
    before = snapshot(engine, world.user.id)
    baseline = engine.pool.checkedout()
    for _ in range(10):
        assert client.get(SUMMARY, headers=world.headers()).status_code == 200
    assert_no_leaks(engine, baseline)
    assert snapshot(engine, world.user.id) == before


def test_sessions_are_closed_when_the_service_fails(client, engine, world, monkeypatch):
    def broken(self, user_id, *, now=None):
        self.session.scalar(text("SELECT 1"))  # the session is in use when it fails
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(dashboard_service.DashboardService, "summary", broken)
    baseline = engine.pool.checkedout()
    for _ in range(3):
        response = client.get(SUMMARY, headers=world.headers())
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert_no_leaks(engine, baseline)


def test_sessions_are_closed_when_a_query_fails(client, engine, world, monkeypatch):
    def failing_query(self, user_id, *, now=None):
        self.session.execute(text("SELECT * FROM no_such_table"))

    monkeypatch.setattr(dashboard_service.DashboardService, "summary", failing_query)
    baseline = engine.pool.checkedout()
    assert client.get(SUMMARY, headers=world.headers()).status_code == 500
    assert_no_leaks(engine, baseline)


def test_unauthenticated_requests_open_no_dashboard_session(client, engine, statements):
    baseline = engine.pool.checkedout()
    for headers in ({}, {"Authorization": "Bearer not-a-jwt"}):
        response = client.get(SUMMARY, headers=headers)
        assert response.status_code == 401
    assert not any(sql.startswith("SET TRANSACTION") for _, sql in statements)
    assert_no_leaks(engine, baseline)


def test_other_endpoints_keep_their_read_write_session(client, world, statements):
    statements.clear()
    response = client.get("/api/v1/auth/me", headers=world.headers())
    assert response.status_code == 200
    assert not any(sql.startswith("SET TRANSACTION") for _, sql in statements)


# ---- development seed ------------------------------------------------------------------------------------

def test_seed_users_match_the_seed_specification(client, engine):
    from seeds import dev_seed

    with Session(engine) as session:
        dev_seed.seed_development_data(session, settings_for(PG_URL))
        session.commit()

    for seed_user in dev_seed.USERS:
        with Session(engine) as session:
            user = UserRepository(session).get_by_email(seed_user.email)
            unread = session.scalar(select(text("count(*)")).select_from(Alert).where(Alert.user_id == user.id, Alert.is_read.is_(False)))
        specs = [t for t in dev_seed.TRANSACTIONS if t.user == seed_user.key]
        assert all(t.days_ago < 30 for t in specs)  # freshly seeded: everything is inside the window
        expected_status = dict.fromkeys(ALL_STATUSES, 0)
        for spec in specs:
            expected_status[spec.outcome.value] += 1
        token = create_access_token(user.id, make_settings(JWT_SECRET_KEY=TEST_JWT_SECRET)).token
        body = client.get(SUMMARY, headers={"Authorization": f"Bearer {token}"}).json()

        assert body["transactions"]["by_status"] == expected_status, seed_user.key
        assert body["transactions"]["total"] == len(specs)
        assert body["transactions"]["approved_amount_paise"] == sum(t.rupees * 100 for t in specs if t.outcome == S.APPROVED)
        assert body["transactions"]["awaiting_action"] == sum(1 for t in specs if t.outcome == S.AWAITING_USER_ACTION)
        assert body["alerts"]["unread"] == unread
