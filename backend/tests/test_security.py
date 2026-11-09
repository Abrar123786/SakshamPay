"""P-6: password hashing and JWT handling (no database needed)."""

import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from argon2 import PasswordHasher

from app.core import security
from app.core.security import (
    AuthenticationNotConfiguredError,
    InvalidTokenError,
    TokenExpiredError,
    create_access_token,
    decode_access_token,
    hash_password,
    password_needs_rehash,
    verify_dummy_password,
    verify_password,
)
from tests.conftest import TEST_JWT_SECRET, make_settings

SETTINGS = make_settings(JWT_SECRET_KEY=TEST_JWT_SECRET)
USER_ID = uuid.UUID("2b0f6f7e-3c41-4c6f-9d55-0a1c2b3d4e5f")


def token_with(claims: dict, key: str = TEST_JWT_SECRET, algorithm: str = "HS256") -> str:
    return jwt.encode(claims, key, algorithm=algorithm)


def now_ts() -> int:
    return int(time.time())


# ---- password hashing -------------------------------------------------------------------------------

def test_production_hasher_is_argon2id_with_rfc9106_parameters():
    hasher = security.password_hasher
    assert hasher.type.name == "ID"
    assert (hasher.memory_cost, hasher.time_cost, hasher.parallelism) == (65536, 3, 4)
    stored = hash_password("correct horse battery")
    assert stored.startswith("$argon2id$v=19$m=65536,t=3,p=4$")


@pytest.mark.usefixtures("fast_password_hashing")
def test_hash_is_salted_and_verifiable():
    first, second = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert first != second  # random salt per hash
    assert "correct horse battery" not in first
    assert verify_password(first, "correct horse battery")
    assert not verify_password(first, "correct horse batterY")


@pytest.mark.parametrize("corrupt", ["", "not-a-hash", "$argon2id$garbage", "$2b$12$bcrypt-style-hash"])
def test_corrupt_hashes_fail_closed_without_raising(corrupt):
    assert verify_password(corrupt, "whatever-password") is False


def test_weaker_hashes_are_flagged_for_rehash():
    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash("pw-1234567890")
    assert password_needs_rehash(weak) is True
    assert password_needs_rehash(hash_password("pw-1234567890")) is False


@pytest.mark.usefixtures("fast_password_hashing")
def test_dummy_verification_runs_a_real_argon2_check(monkeypatch):
    calls = []
    original = security.verify_password
    monkeypatch.setattr(security, "verify_password", lambda h, p: calls.append(h) or original(h, p))
    verify_dummy_password("anything")
    assert len(calls) == 1 and calls[0].startswith("$argon2id$")  # a full Argon2id verification ran


# ---- token creation -------------------------------------------------------------------------------

def test_token_has_exactly_the_minimal_claims():
    issued = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
    access = create_access_token(USER_ID, SETTINGS, now=issued)
    claims = jwt.decode(access.token, TEST_JWT_SECRET, algorithms=["HS256"], options={"verify_exp": False, "verify_iat": False})
    assert claims == {"sub": str(USER_ID), "iat": int(issued.timestamp()), "exp": int(issued.timestamp()) + 1800}
    assert jwt.get_unverified_header(access.token)["alg"] == "HS256"
    assert access.expires_in == 1800 and access.expires_at == issued + timedelta(minutes=30)


def test_lifetime_follows_settings():
    access = create_access_token(USER_ID, make_settings(JWT_SECRET_KEY=TEST_JWT_SECRET, ACCESS_TOKEN_EXPIRE_MINUTES=5))
    assert access.expires_in == 300


def test_valid_token_round_trips():
    assert decode_access_token(create_access_token(USER_ID, SETTINGS).token, SETTINGS) == USER_ID


# ---- token rejection ------------------------------------------------------------------------------

def test_expired_token_is_rejected():
    token = token_with({"sub": str(USER_ID), "iat": now_ts() - 3600, "exp": now_ts() - 1})
    with pytest.raises(TokenExpiredError):
        decode_access_token(token, SETTINGS)


def test_invalid_signature_is_rejected():
    token = token_with({"sub": str(USER_ID), "iat": now_ts(), "exp": now_ts() + 60}, key="another-secret-" + "x" * 40)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, SETTINGS)


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b.c", "eyJhbGciOiJIUzI1NiJ9.e30", "Bearer abc.def.ghi"])
def test_malformed_tokens_are_rejected(token):
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, SETTINGS)


@pytest.mark.parametrize(
    "claims",
    [
        {"iat": "now", "exp": "+60"},                    # missing sub
        {"sub": "", "iat": "now", "exp": "+60"},          # empty sub
        {"sub": "not-a-uuid", "iat": "now", "exp": "+60"},
        {"sub": 12345, "iat": "now", "exp": "+60"},       # non-string sub
        {"sub": "uuid", "exp": "+60"},                    # missing iat
        {"sub": "uuid", "iat": "now"},                    # missing exp
        {"sub": "uuid", "iat": "+3600", "exp": "+7200"},  # issued in the future
    ],
)
def test_tokens_with_missing_or_invalid_claims_are_rejected(claims):
    values = {"now": now_ts(), "+60": now_ts() + 60, "+3600": now_ts() + 3600, "+7200": now_ts() + 7200}
    payload = {k: (str(USER_ID) if v == "uuid" else values.get(v, v) if isinstance(v, str) else v) for k, v in claims.items()}
    with pytest.raises(InvalidTokenError):
        decode_access_token(token_with(payload), SETTINGS)


@pytest.mark.parametrize("algorithm", ["HS512", "HS384"])
def test_other_algorithms_are_rejected(algorithm):
    token = token_with({"sub": str(USER_ID), "iat": now_ts(), "exp": now_ts() + 60}, key=TEST_JWT_SECRET * 2, algorithm=algorithm)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, make_settings(JWT_SECRET_KEY=TEST_JWT_SECRET * 2))


def test_unsigned_alg_none_token_is_rejected():
    token = jwt.encode({"sub": str(USER_ID), "iat": now_ts(), "exp": now_ts() + 60}, None, algorithm="none")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, SETTINGS)


# ---- configuration --------------------------------------------------------------------------------

@pytest.mark.parametrize("secret", [None, "", "too-short-secret"])
def test_no_fallback_secret(secret):
    settings = make_settings(JWT_SECRET_KEY=secret)
    with pytest.raises(AuthenticationNotConfiguredError):
        create_access_token(USER_ID, settings)
    with pytest.raises(AuthenticationNotConfiguredError):
        decode_access_token("x.y.z", settings)


def test_lockout_settings_defaults_and_bounds():
    settings = make_settings()
    assert (settings.LOGIN_MAX_FAILED_ATTEMPTS, settings.LOGIN_LOCKOUT_MINUTES) == (5, 15)
    with pytest.raises(ValueError):
        make_settings(LOGIN_MAX_FAILED_ATTEMPTS=0)
