"""P-6: registration, login and the protected endpoint against migrated PostgreSQL.

Runs only with TEST_DATABASE_URL (see tests/pg.py). Every test uses its own email
addresses inside one throwaway schema built by the real Alembic migrations.
"""

import logging
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.main import create_app
from app.models import Alert, AlertType, AuditLog, User
from app.repositories import UserRepository
from app.repositories.errors import EmailAlreadyRegisteredError
from tests.conftest import TEST_JWT_SECRET, make_settings
from tests.pg import database_for, require_postgres_url, throwaway_schema

PG_URL = require_postgres_url()
pytestmark = pytest.mark.usefixtures("fast_password_hashing")

REGISTER, LOGIN, ME = "/api/v1/auth/register", "/api/v1/auth/login", "/api/v1/auth/me"
PASSWORD = "a-long-passphrase"
SAFE_PROFILE_FIELDS = {"id", "full_name", "email", "phone_number", "is_active", "created_at"}


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


def unique_email() -> str:
    return f"user.{uuid.uuid4().hex[:10]}@example.com"


def register(client, email=None, password=PASSWORD, **extra):
    body = {"full_name": "Asha Rao", "email": email or unique_email(), "password": password, **extra}
    return client.post(REGISTER, json=body)


def login(client, email, password=PASSWORD):
    return client.post(LOGIN, json={"email": email, "password": password})


def stored_user(engine, email) -> User:
    with Session(engine) as session:
        return UserRepository(session).get_by_email(email)


def audit_actions(engine, user_id) -> list[tuple[str, str | None]]:
    with Session(engine) as session:
        rows = session.scalars(select(AuditLog).where(AuditLog.user_id == user_id).order_by(AuditLog.id))
        return [(r.action, (r.event_metadata or {}).get("reason")) for r in rows]


# ==== registration ===============================================================================

def test_successful_registration(client, engine):
    email = unique_email()
    response = register(client, email=email.upper(), phone_number="+91 98765-43210")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == SAFE_PROFILE_FIELDS
    assert body["email"] == email and body["phone_number"] == "+919876543210" and body["is_active"] is True
    user = stored_user(engine, email)
    assert str(user.id) == body["id"]
    assert ("USER_REGISTERED", None) in audit_actions(engine, user.id)


def test_password_is_stored_only_as_an_argon2id_hash(client, engine):
    email = unique_email()
    response = register(client, email=email)
    user = stored_user(engine, email)
    assert user.password_hash.startswith("$argon2id$") and PASSWORD not in user.password_hash
    assert verify_password(user.password_hash, PASSWORD)
    assert "argon2" not in response.text and PASSWORD not in response.text
    with engine.connect() as connection:  # nowhere in the row
        row = connection.execute(text("SELECT row_to_json(u)::text FROM users u WHERE email = :e"), {"e": email}).scalar()
    assert PASSWORD not in row


def test_duplicate_email_is_409_case_insensitively(client):
    email = unique_email()
    assert register(client, email=email).status_code == 201
    response = register(client, email=email.title())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


def test_duplicate_phone_is_409(client):
    phone = f"+9190{uuid.uuid4().int % 10**8:08d}"
    assert register(client, phone_number=phone).status_code == 201
    response = register(client, phone_number=phone)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PHONE_ALREADY_REGISTERED"


def test_concurrent_duplicate_registrations_create_exactly_one_account(client, engine):
    email = unique_email()
    statuses = []
    barrier = threading.Barrier(5)

    def attempt():
        barrier.wait()
        statuses.append(register(client, email=email).status_code)

    threads = [threading.Thread(target=attempt) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(statuses) == [201, 409, 409, 409, 409]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM users WHERE email = :e"), {"e": email}).scalar() == 1


def test_uncommitted_duplicate_waits_then_conflicts(engine):
    """The database, not a pre-check, decides: a second insert blocks on the first, then fails."""
    email = unique_email()
    hashed = "$argon2id$v=19$m=8192,t=1,p=1$" + "a" * 60
    first = Session(engine)
    UserRepository(first).create(full_name="First", email=email, password_hash=hashed)
    outcome = {}

    def second_insert():
        with Session(engine) as second:
            try:
                UserRepository(second).create(full_name="Second", email=email, password_hash=hashed)
                second.commit()
                outcome["result"] = "created"
            except EmailAlreadyRegisteredError:
                outcome["result"] = "conflict"

    worker = threading.Thread(target=second_insert)
    worker.start()
    worker.join(timeout=0.5)
    assert worker.is_alive()  # blocked on the first transaction's row
    first.commit()
    first.close()
    worker.join(timeout=10)
    assert outcome["result"] == "conflict"


# ==== login ==========================================================================================

def test_successful_login_returns_a_valid_token(client, engine):
    email = unique_email()
    user_id = register(client, email=email).json()["id"]
    before = int(time.time())
    response = login(client, email.upper())
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "expires_at"}
    assert body["token_type"] == "bearer" and body["expires_in"] == 1800
    claims = jwt.decode(body["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    assert set(claims) == {"sub", "iat", "exp"} and claims["sub"] == user_id
    assert before - 1 <= claims["iat"] <= int(time.time()) and claims["exp"] - claims["iat"] == 1800
    assert datetime.fromisoformat(body["expires_at"]).timestamp() == claims["exp"]
    assert response.headers["cache-control"] == "no-store"
    user = stored_user(engine, email)
    assert user.last_login_at is not None and user.failed_login_count == 0
    assert ("LOGIN_SUCCEEDED", None) in audit_actions(engine, user.id)


def test_wrong_password_and_unknown_email_get_identical_responses(client, engine):
    email = unique_email()
    register(client, email=email)
    wrong = login(client, email, "not-the-password")
    unknown = login(client, unique_email(), "not-the-password")
    assert wrong.status_code == unknown.status_code == 401
    strip = lambda r: {**r.json()["error"], "request_id": None}  # noqa: E731
    assert strip(wrong) == strip(unknown) == {"code": "INVALID_CREDENTIALS", "message": "Invalid email or password.", "request_id": None}
    assert set(wrong.headers) - {"x-request-id", "content-length", "date"} == set(unknown.headers) - {"x-request-id", "content-length", "date"}
    assert stored_user(engine, email).failed_login_count == 1
    assert ("LOGIN_FAILED", "wrong_password") in audit_actions(engine, stored_user(engine, email).id)


def test_unknown_email_is_audited_without_storing_the_email(client, engine):
    email = unique_email()
    login(client, email)
    with Session(engine) as session:
        entry = session.scalars(select(AuditLog).where(AuditLog.action == "LOGIN_FAILED").order_by(AuditLog.id.desc())).first()
    assert entry.user_id is None and entry.event_metadata == {"reason": "unknown_account"}
    assert email not in str(entry.event_metadata) and entry.actor_type == "ANONYMOUS"


def test_deactivated_account_cannot_log_in_or_use_old_tokens(client, engine):
    email = unique_email()
    register(client, email=email)
    token = login(client, email).json()["access_token"]
    with Session(engine) as session:
        UserRepository(session).deactivate(UserRepository(session).get_by_email(email))
        session.commit()
    response = login(client, email)
    assert response.status_code == 401 and response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert ("LOGIN_FAILED", "inactive_account") in audit_actions(engine, stored_user(engine, email).id)
    assert client.get(ME, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_lockout_after_repeated_failures(client, engine):
    email = unique_email()
    register(client, email=email)
    for _ in range(5):
        assert login(client, email, "wrong-password-1").status_code == 401
    user = stored_user(engine, email)
    assert user.locked_until is not None and user.locked_until > datetime.now(UTC) + timedelta(minutes=14)
    assert user.failed_login_count == 0  # counter restarts when the lock is applied

    # While locked, even the correct password gets the same generic answer.
    locked = login(client, email)
    assert locked.status_code == 401 and locked.json()["error"]["code"] == "INVALID_CREDENTIALS"
    actions = audit_actions(engine, user.id)
    assert actions.count(("LOGIN_FAILED", "wrong_password")) == 5
    assert ("ACCOUNT_LOCKED", None) in actions and ("LOGIN_FAILED", "account_locked") in actions
    with Session(engine) as session:
        alert = session.scalar(select(Alert).where(Alert.user_id == user.id))
    assert alert.alert_type == AlertType.ACCOUNT_LOCKED

    # After the lock expires, the correct password works and the state resets.
    with engine.begin() as connection:
        connection.execute(text("UPDATE users SET locked_until = now() - interval '1 second' WHERE email = :e"), {"e": email})
    assert login(client, email).status_code == 200
    user = stored_user(engine, email)
    assert user.locked_until is None and user.failed_login_count == 0


def test_successful_login_resets_the_failure_counter(client, engine):
    email = unique_email()
    register(client, email=email)
    login(client, email, "wrong-password-1")
    login(client, email, "wrong-password-2")
    assert stored_user(engine, email).failed_login_count == 2
    assert login(client, email).status_code == 200
    assert stored_user(engine, email).failed_login_count == 0


def test_weaker_hash_is_upgraded_on_login(client, engine, monkeypatch):
    from argon2 import PasswordHasher

    from app.core import security

    email = unique_email()
    register(client, email=email)  # stored with the test hasher (t=1)
    monkeypatch.setattr(security, "password_hasher", PasswordHasher(time_cost=2, memory_cost=8192, parallelism=1))
    assert login(client, email).status_code == 200
    assert ",t=2," in stored_user(engine, email).password_hash


# ==== protected endpoint ===============================================================================

def test_me_returns_only_the_safe_profile(client):
    email = unique_email()
    registered = register(client, email=email, phone_number=f"+9191{uuid.uuid4().int % 10**8:08d}").json()
    token = login(client, email).json()["access_token"]
    response = client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == registered
    assert set(response.json()) == SAFE_PROFILE_FIELDS
    for hidden in ("password", "argon2", "failed_login_count", "locked_until", "last_login_at"):
        assert hidden not in response.text


def test_token_for_nonexistent_user_is_rejected(client):
    now = int(time.time())
    token = jwt.encode({"sub": str(uuid.uuid4()), "iat": now, "exp": now + 60}, TEST_JWT_SECRET, algorithm="HS256")
    response = client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401 and response.json()["error"]["code"] == "INVALID_TOKEN"


def test_expired_token_for_real_user_is_rejected(client, engine):
    email = unique_email()
    user_id = register(client, email=email).json()["id"]
    past = int(time.time()) - 3600
    token = jwt.encode({"sub": user_id, "iat": past, "exp": past + 1800}, TEST_JWT_SECRET, algorithm="HS256")
    response = client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401 and response.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_identity_comes_only_from_the_token(client):
    alice, bob = unique_email(), unique_email()
    register(client, email=alice)
    bob_id = register(client, email=bob).json()["id"]
    token = login(client, alice).json()["access_token"]
    response = client.request("GET", ME, headers={"Authorization": f"Bearer {token}"},
                              params={"user_id": bob_id}, json={"user_id": bob_id, "sub": bob_id})
    assert response.json()["email"] == alice


# ==== secrets never leak ==================================================================================

def test_passwords_and_tokens_are_never_logged(client, caplog):
    caplog.set_level(logging.DEBUG)
    email, password = unique_email(), "Very-Distinctive-Passphrase-42"
    register(client, email=email, password=password)
    login(client, email, "Another-Distinctive-Wrong-Guess-7")
    token = login(client, email, password).json()["access_token"]
    client.get(ME, headers={"Authorization": f"Bearer {token}"})
    app_records = [r for r in caplog.records if r.name.startswith(("sakshampay", "uvicorn", "sqlalchemy"))]
    logged = " ".join(r.getMessage() + " " + str(vars(r)) for r in app_records)
    assert app_records
    for secret in (password, "Another-Distinctive-Wrong-Guess-7", token, TEST_JWT_SECRET):
        assert secret not in logged


def test_audit_entries_contain_no_credentials(client, engine):
    email = unique_email()
    register(client, email=email)
    login(client, email, "wrong-password-9")
    token = login(client, email).json()["access_token"]
    with engine.connect() as connection:
        dump = " ".join(connection.execute(text("SELECT row_to_json(a)::text FROM audit_logs a")).scalars())
    assert PASSWORD not in dump and "wrong-password-9" not in dump and token not in dump
