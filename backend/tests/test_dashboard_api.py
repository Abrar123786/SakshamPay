"""P-9: GET /api/v1/dashboard/summary without a database.

Authentication is checked before the database is touched (P-6), so missing and
bad tokens are tested with a session that fails if used. The response contract
is tested with the current user and the service replaced.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.database.session import get_db, get_read_only_db
from app.main import create_app
from app.routes.dependencies import get_current_user
from app.schemas.dashboard import DashboardSummary
from app.services import dashboard as dashboard_service
from tests.conftest import TEST_JWT_SECRET, make_settings

SUMMARY = "/api/v1/dashboard/summary"
STATUSES = ["INITIATED", "ANALYSED", "AWAITING_USER_ACTION", "APPROVED", "CANCELLED", "EXPIRED", "FAILED"]


class UnusableSession:
    def __getattr__(self, name):
        raise AssertionError(f"the database must not be touched (attempted session.{name})")


class FakeUser:
    id = uuid.UUID("9f1c2a5e-0000-4000-8000-000000000001")
    is_active = True


def make_app(read_only_sessions=None):
    """No database: both the auth session and the dashboard's read-only session are unusable."""
    app = create_app(make_settings(JWT_SECRET_KEY=TEST_JWT_SECRET))
    app.dependency_overrides[get_db] = lambda: UnusableSession()

    def read_only_session():
        if read_only_sessions is not None:
            read_only_sessions.append("opened")
        return UnusableSession()

    app.dependency_overrides[get_read_only_db] = read_only_session
    return app


@pytest.fixture
def client():
    with TestClient(make_app(), raise_server_exceptions=False) as test_client:
        yield test_client


def token(**claims):
    now = datetime.now(UTC)
    body = {"sub": str(uuid.uuid4()), "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=5)).timestamp()), **claims}
    return jwt.encode(body, TEST_JWT_SECRET, algorithm="HS256")


# ---- authentication -----------------------------------------------------------------------------

def test_requires_a_token(client):
    response = client.get(SUMMARY)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("auth", "code"),
    [
        ("Bearer not-a-jwt", "INVALID_TOKEN"),
        (f"Bearer {jwt.encode({'sub': str(uuid.uuid4()), 'iat': 1, 'exp': 9999999999}, 'x' * 40, algorithm='HS256')}", "INVALID_TOKEN"),
        (f"Bearer {token(exp=int((datetime.now(UTC) - timedelta(minutes=1)).timestamp()))}", "TOKEN_EXPIRED"),
        (f"Bearer {token(sub='not-a-uuid')}", "INVALID_TOKEN"),
    ],
    ids=["malformed", "wrong-signature", "expired", "bad-subject"],
)
def test_rejects_bad_tokens_before_touching_the_database(client, auth, code):
    response = client.get(SUMMARY, headers={"Authorization": auth})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == code


def test_a_rejected_request_never_opens_the_dashboard_session():
    opened = []
    with TestClient(make_app(read_only_sessions=opened), raise_server_exceptions=False) as test_client:
        assert test_client.get(SUMMARY).status_code == 401
        assert test_client.get(SUMMARY, headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
    assert opened == []  # CurrentUser is resolved first; the read-only session is created only after it succeeds


def test_only_get_is_allowed(client):
    assert client.post(SUMMARY).status_code == 405


# ---- response contract (service replaced) --------------------------------------------------------

@pytest.fixture
def stubbed_client(monkeypatch):
    calls = []

    def fake_summary(self, user_id, *, now=None):
        calls.append(user_id)
        end = datetime(2026, 11, 9, 18, 0, tzinfo=UTC)
        return DashboardSummary.model_validate(
            {
                "period": {"days": 30, "start": end - timedelta(days=30), "end": end},
                "transactions": {
                    "total": 3,
                    "by_status": {"APPROVED": 2, "CANCELLED": 1},
                    "awaiting_action": 0,
                    "approved_amount_paise": 123_450,
                },
                "alerts": {"unread": 2},
            }
        )

    monkeypatch.setattr(dashboard_service.DashboardService, "summary", fake_summary)
    app = make_app()
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        test_client.calls = calls
        yield test_client


def test_response_shape_and_every_status_key(stubbed_client):
    response = stubbed_client.get(SUMMARY, headers={"Authorization": "Bearer stub"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"period", "transactions", "alerts"}
    assert body["period"] == {"days": 30, "start": "2026-10-10T18:00:00Z", "end": "2026-11-09T18:00:00Z"}
    assert list(body["transactions"]["by_status"]) == STATUSES
    assert body["transactions"]["by_status"] == {s: {"APPROVED": 2, "CANCELLED": 1}.get(s, 0) for s in STATUSES}
    assert body["transactions"]["approved_amount_paise"] == 123_450
    assert isinstance(body["transactions"]["approved_amount_paise"], int)
    assert body["alerts"] == {"unread": 2}
    assert "risk_levels" not in body and "risk" not in str(body).lower()  # deferred until the risk engine exists


def test_uses_the_user_from_the_token(stubbed_client):
    stubbed_client.get(SUMMARY, headers={"Authorization": "Bearer stub"})
    assert stubbed_client.calls == [FakeUser.id]


def test_ignores_query_parameters(stubbed_client):
    response = stubbed_client.get(SUMMARY, params={"user_id": str(uuid.uuid4()), "days": 365}, headers={"Authorization": "Bearer stub"})
    assert response.status_code == 200
    assert response.json()["period"]["days"] == 30
    assert stubbed_client.calls == [FakeUser.id]


def test_is_never_cached(stubbed_client):
    response = stubbed_client.get(SUMMARY, headers={"Authorization": "Bearer stub"})
    assert response.headers["cache-control"] == "no-store"


def test_status_counts_reject_unknown_keys():
    with pytest.raises(ValueError):
        DashboardSummary.model_validate(
            {
                "period": {"days": 30, "start": datetime.now(UTC), "end": datetime.now(UTC)},
                "transactions": {"total": 0, "by_status": {"PENDING": 1}, "awaiting_action": 0, "approved_amount_paise": 0},
                "alerts": {"unread": 0},
            }
        )


# ---- documentation -----------------------------------------------------------------------------

def test_openapi_documents_the_endpoint(client):
    spec = client.get("/openapi.json").json()
    operation = spec["paths"][SUMMARY]["get"]
    assert operation["tags"] == ["Dashboard"]
    assert {"200", "401", "503"} <= set(operation["responses"])
    assert operation["security"] == [{"BearerToken": []}]
    statuses = spec["components"]["schemas"]["TransactionStatusCounts"]["properties"]
    assert list(statuses) == STATUSES


def test_create_access_token_still_works_for_this_router():
    # Guard: the dashboard reuses P-6 tokens unchanged.
    settings = make_settings(JWT_SECRET_KEY=TEST_JWT_SECRET)
    assert create_access_token(uuid.uuid4(), settings).token.count(".") == 2
