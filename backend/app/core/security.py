"""Password hashing (Argon2id) and access tokens (JWT, HS256).

Passwords
    argon2-cffi's ``PasswordHasher`` with its default RFC 9106 parameters
    (Argon2id, 64 MiB memory, 3 iterations, 4 lanes, 16-byte random salt).
    ``verify_password`` never raises for a wrong password or a corrupt hash; it
    returns False. ``verify_dummy_password`` spends the same time when there is no
    user to check, so response time does not reveal whether an email exists.

Access tokens
    Claims are exactly ``sub`` (user UUID), ``iat`` and ``exp`` (P-1: 30 minutes,
    no refresh tokens). Decoding pins the algorithm to HS256 (so ``alg: none`` and
    algorithm switching are rejected), requires all three claims and checks the
    signature, expiry, issue time and that ``sub`` is a UUID.

    The signing key is ``JWT_SECRET_KEY``. There is no fallback: without a key of
    at least 32 characters, issuing or checking tokens raises
    AuthenticationNotConfiguredError (503). Tokens are never logged.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import MIN_JWT_SECRET_LENGTH, Settings
from app.core.exceptions import AppError

TOKEN_TYPE = "bearer"
REQUIRED_CLAIMS = ("sub", "iat", "exp")
BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}

# Module-level so tests can substitute a faster (still Argon2id) hasher.
password_hasher = PasswordHasher()


# ---- errors ---------------------------------------------------------------------------------

class AuthenticationError(AppError):
    status_code = 401
    code = "NOT_AUTHENTICATED"
    message = "Authentication is required."
    headers = BEARER_CHALLENGE


class InvalidCredentialsError(AuthenticationError):
    code = "INVALID_CREDENTIALS"
    message = "Invalid email or password."
    headers = None  # a login failure is not a bearer-token challenge


class InvalidTokenError(AuthenticationError):
    code = "INVALID_TOKEN"
    message = "The access token is invalid."


class TokenExpiredError(AuthenticationError):
    code = "TOKEN_EXPIRED"
    message = "The access token has expired. Please sign in again."


class AuthenticationNotConfiguredError(AppError):
    status_code = 503
    code = "AUTH_NOT_CONFIGURED"
    message = "Authentication is not available right now."


# ---- passwords -----------------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True when the stored hash used weaker parameters than the current hasher."""
    try:
        return password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


@lru_cache(maxsize=4)
def _dummy_hash(parameters: tuple) -> str:
    return password_hasher.hash("sakshampay-timing-equaliser")


def verify_dummy_password(password: str) -> None:
    """Spend the same effort as a real verification (used when there is no user)."""
    hasher = password_hasher
    verify_password(_dummy_hash((hasher.time_cost, hasher.memory_cost, hasher.parallelism)), password)


# ---- tokens -------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class AccessToken:
    token: str
    expires_at: datetime
    expires_in: int  # seconds


def _signing_key(settings: Settings) -> str:
    secret = settings.JWT_SECRET_KEY.get_secret_value() if settings.JWT_SECRET_KEY else ""
    if len(secret) < MIN_JWT_SECRET_LENGTH:
        raise AuthenticationNotConfiguredError()
    return secret


def ensure_token_signing_configured(settings: Settings) -> None:
    """Raise AuthenticationNotConfiguredError (503) unless a usable JWT key is set."""
    _signing_key(settings)


def create_access_token(user_id: uuid.UUID, settings: Settings, *, now: datetime | None = None) -> AccessToken:
    issued_at = (now or datetime.now(UTC)).replace(microsecond=0)
    lifetime = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    expires_at = issued_at + lifetime
    claims = {"sub": str(user_id), "iat": int(issued_at.timestamp()), "exp": int(expires_at.timestamp())}
    token = jwt.encode(claims, _signing_key(settings), algorithm=settings.JWT_ALGORITHM)
    return AccessToken(token=token, expires_at=expires_at, expires_in=int(lifetime.total_seconds()))


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    """Return the user ID in a valid token; raise TokenExpiredError or InvalidTokenError otherwise."""
    key = _signing_key(settings)
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": list(REQUIRED_CLAIMS)},
        )
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError() from None
    except jwt.PyJWTError:
        raise InvalidTokenError() from None
    try:
        return uuid.UUID(claims["sub"])
    except (ValueError, TypeError, AttributeError):
        raise InvalidTokenError() from None
