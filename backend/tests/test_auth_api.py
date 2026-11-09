"""P-6: auth endpoints at the HTTP level without a database.

Input validation, bearer-token handling and configuration errors are all decided
before any query runs, so they are tested here with the session dependency
replaced by a placeholder that fails loudly if it is ever used.
"""

import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from app.database.session import get_db
from app.main import create_app
from tests.conftest import TEST_JWT_SECRET, make_settings

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
VALID_REGISTRATION = {
    "full_name": "Asha Rao",
    "email": "asha.rao@example.com",
    "phone_number": "+919876543210",
    "password": "a-long-passphrase",
}


class UnusableSession:
    def __getattr__(self, name):
        raise AssertionError(f"the database must not be touched (attempted session.{name})")


def make_client(**settings_overrides) -> TestClient:
    app = create_app(make_settings(**{"JWT_SECRET_KEY": TEST_JWT_SECRET, **settings_overrides}))
    app.dependency_overrides[get_db] = lambda: UnusableSession()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client():
    with make_client() as test_client:
        yield test_client


def error_code(response):
    return response.json()["error"]["code"]


# ---- registration input ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"email": "not-an-email"}, "email"),
        ({"email": "a@b"}, "email"),
        ({"email": "x" * 250 + "@example.com"}, "email"),
        ({"password": "short"}, "password"),
        ({"password": "x" * 129}, "password"),
        ({"password": "          "}, "password"),
        ({"full_name": "   "}, "full_name"),
        ({"full_name": "x" * 101}, "full_name"),
        ({"phone_number": "98765 43210"}, "phone_number"),
        ({"phone_number": "+0123456789"}, "phone_number"),
    ],
)
def test_invalid_registration_input_is_rejected(client, change, field):
    response = client.post(REGISTER, json={**VALID_REGISTRATION, **change})
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"
    assert field in {d["location"][-1] for d in response.json()["error"]["details"]}


@pytest.mark.parametrize("missing", ["full_name", "email", "password"])
def test_required_registration_fields(client, missing):
    body = {k: v for k, v in VALID_REGISTRATION.items() if k != missing}
    assert client.post(REGISTER, json=body).status_code == 422


@pytest.mark.parametrize("smuggled", [{"id": str(uuid.uuid4())}, {"is_active": False}, {"password_hash": "$argon2id$x"}])
def test_server_owned_fields_are_refused(client, smuggled):
    response = client.post(REGISTER, json={**VALID_REGISTRATION, **smuggled})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["type"] == "extra_forbidden"


def test_password_equal_to_email_is_refused(client):
    body = {**VALID_REGISTRATION, "email": "long.address@example.com", "password": "Long.Address@example.com"}
    assert client.post(REGISTER, json=body).status_code == 422


def test_validation_errors_never_echo_the_password(client):
    response = client.post(REGISTER, json={**VALID_REGISTRATION, "password": "tiny-pw"})
    assert response.status_code == 422
    assert "tiny-pw" not in response.text


# ---- login input --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": "asha.rao@example.com"},
        {"password": "a-long-passphrase"},
        {"email": "not-an-email", "password": "a-long-passphrase"},
        {"email": "asha.rao@example.com", "password": ""},
        {"email": "asha.rao@example.com", "password": "x" * 129},
        {"email": "asha.rao@example.com", "password": "a-long-passphrase", "remember_me": True},
        {"email": ["asha.rao@example.com"], "password": "a-long-passphrase"},
    ],
)
def test_malformed_login_input_is_rejected(client, body):
    response = client.post(LOGIN, json=body)
    assert response.status_code == 422 and error_code(response) == "VALIDATION_ERROR"


def test_non_json_login_body_is_rejected(client):
    response = client.post(LOGIN, content=b"email=a&password=b", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == 422


# ---- protected endpoint without a valid token ------------------------------------------------------------

def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def signed(claims: dict, key: str = TEST_JWT_SECRET) -> str:
    return jwt.encode(claims, key, algorithm="HS256")


def test_missing_token_is_401_with_bearer_challenge(client):
    response = client.get(ME)
    assert response.status_code == 401
    assert error_code(response) == "NOT_AUTHENTICATED"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("header", ["Basic dXNlcjpwYXNz", "Bearer", "Token abc", ""])
def test_non_bearer_authorization_is_401(client, header):
    response = client.get(ME, headers={"Authorization": header})
    assert response.status_code == 401 and error_code(response) == "NOT_AUTHENTICATED"


@pytest.mark.parametrize(
    ("token", "code"),
    [
        ("not-a-jwt", "INVALID_TOKEN"),
        (signed({"sub": str(uuid.uuid4()), "iat": int(time.time()), "exp": int(time.time()) + 60}, key="wrong-" + "k" * 40), "INVALID_TOKEN"),
        (signed({"iat": int(time.time()), "exp": int(time.time()) + 60}), "INVALID_TOKEN"),
        (signed({"sub": "not-a-uuid", "iat": int(time.time()), "exp": int(time.time()) + 60}), "INVALID_TOKEN"),
        (signed({"sub": str(uuid.uuid4()), "iat": int(time.time()) - 3600, "exp": int(time.time()) - 10}), "TOKEN_EXPIRED"),
    ],
    ids=["malformed", "bad-signature", "no-subject", "bad-subject", "expired"],
)
def test_bad_tokens_are_401_before_any_database_access(client, token, code):
    response = client.get(ME, headers=bearer(token))
    assert response.status_code == 401
    assert error_code(response) == code
    assert response.headers["www-authenticate"] == "Bearer"
    assert token not in response.text


def test_unconfigured_jwt_secret_gives_503_not_a_fallback():
    with make_client(JWT_SECRET_KEY=None) as client:
        token = signed({"sub": str(uuid.uuid4()), "iat": int(time.time()), "exp": int(time.time()) + 60})
        assert error_code(client.get(ME, headers=bearer(token))) == "AUTH_NOT_CONFIGURED"
        response = client.post(LOGIN, json={"email": "asha.rao@example.com", "password": "a-long-passphrase"})
        assert response.status_code == 503 and error_code(response) == "AUTH_NOT_CONFIGURED"


def test_auth_endpoints_are_documented_with_bearer_security(client):
    spec = client.get("/openapi.json").json()
    assert {"/api/v1/auth/register", "/api/v1/auth/login", "/api/v1/auth/me"} <= set(spec["paths"])
    assert spec["paths"]["/api/v1/auth/me"]["get"]["security"] == [{"BearerToken": []}]
    profile = spec["components"]["schemas"]["UserProfile"]["properties"]
    assert "password_hash" not in profile and "failed_login_count" not in profile
