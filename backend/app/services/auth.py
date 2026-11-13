"""Authentication service: registration and login.

Owns the database transaction for each operation (P-3 convention: services commit,
repositories only flush). Uses the P-5 repositories; nothing here builds SQL.

Login never reveals why it failed. Unknown email, wrong password, locked account
and deactivated account all produce the same InvalidCredentialsError, and every
path performs one full Argon2id verification so response time does not reveal
which case occurred. The real reason is recorded only in the audit log.

Rate limits (P-1: "per account and IP prefix"):
  * per account: LOGIN_MAX_FAILED_ATTEMPTS failures lock the account for
    LOGIN_LOCKOUT_MINUTES (always on; reported as INVALID_CREDENTIALS);
  * per network (LOGIN_PREFIX_LIMIT_ENABLED, off by default): LOGIN_PREFIX_FAILURE_LIMIT
    failed logins from one /24 (IPv6 /48), any account or unknown email, in 15 minutes
    give 429 TOO_MANY_LOGIN_ATTEMPTS. It does not depend on the account, so it reveals
    nothing about which emails exist. Counted from LOGIN_FAILED audit rows (which already
    hold the truncated network) under a per-network advisory lock, so concurrent failures
    are counted exactly. At the limit even a correct password is refused (the limit must
    not confirm a right guess) and nothing is recorded: no audit row, no change to the
    account's failure counter.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.security import (
    AccessToken,
    InvalidCredentialsError,
    create_access_token,
    ensure_token_signing_configured,
    hash_password,
    password_needs_rehash,
    verify_dummy_password,
    verify_password,
)
from app.models import AlertSeverity, AlertType, AuditActorType, User
from app.repositories.locks import LOGIN_PREFIX, advisory_xact_lock
from app.utils.privacy import truncate_ip_address
from app.repositories import AlertRepository, AuditLogRepository, UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest

logger = logging.getLogger("sakshampay.auth")

NETWORK_WINDOW = timedelta(minutes=15)  # same window as the account lockout and the Verify limits


class TooManyLoginAttemptsError(AppError):
    status_code = 429
    code = "TOO_MANY_LOGIN_ATTEMPTS"
    message = "Too many unsuccessful sign-in attempts. Please wait a few minutes and try again."


@dataclass(frozen=True)
class ClientInfo:
    ip_address: str | None  # truncated to a network by the audit repository
    user_agent: str | None

    @classmethod
    def from_request(cls, request: Request) -> "ClientInfo":
        return cls(
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


class AuthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.audit = AuditLogRepository(session)
        self.alerts = AlertRepository(session)

    # ---- registration --------------------------------------------------------------------------

    def register(self, request: RegisterRequest, *, client: ClientInfo) -> User:
        """Create an account. Duplicate email or phone raises a 409 error; concurrent
        duplicates are resolved by the database's unique constraints."""
        user = self.users.create(
            full_name=request.full_name,
            email=request.email,
            phone_number=request.phone_number,
            password_hash=hash_password(request.password.get_secret_value()),
        )
        self.audit.record(
            action="USER_REGISTERED",
            actor_type=AuditActorType.USER,
            user_id=user.id,
            entity_type="user",
            entity_id=user.id,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
        )
        self.session.commit()
        logger.info("User registered", extra={"user_id": str(user.id)})
        return user

    # ---- login ------------------------------------------------------------------------------------

    def login(self, request: LoginRequest, *, client: ClientInfo) -> tuple[User, AccessToken]:
        ensure_token_signing_configured(self.settings)  # fail with 503 before touching any account
        now = datetime.now(UTC)
        password = request.password.get_secret_value()
        network = self._limited_network(client)
        if network and self._network_failures(network, now) >= self.settings.LOGIN_PREFIX_FAILURE_LIMIT:
            raise TooManyLoginAttemptsError()  # cheap early answer; the locked check below decides

        # One Argon2id verification on every path, with no network lock held.
        user = self.users.get_by_email(request.email)
        if user is None:
            verify_dummy_password(password)
            failure = "unknown_account"
        elif user.locked_until is not None and user.locked_until > now:
            verify_dummy_password(password)  # passwords are not even checked while locked
            failure = "account_locked"
        else:
            failure = None if verify_password(user.password_hash, password) else "wrong_password"

        if network:
            # Before anything is written: count and record under one per-network lock.
            advisory_xact_lock(self.session, LOGIN_PREFIX, network)
            if self._network_failures(network, now) >= self.settings.LOGIN_PREFIX_FAILURE_LIMIT:
                logger.info("Login refused by the network limit")
                raise TooManyLoginAttemptsError()

        if failure in ("unknown_account", "account_locked"):
            self._fail(user, failure, client)

        if failure == "wrong_password":
            locked_now = self.users.record_failed_login(
                user,
                now=now,
                max_attempts=self.settings.LOGIN_MAX_FAILED_ATTEMPTS,
                lockout=timedelta(minutes=self.settings.LOGIN_LOCKOUT_MINUTES),
            )
            if locked_now:
                self._record_lockout(user, client)
            self._fail(user, "wrong_password", client)

        if not user.is_active:
            self._fail(user, "inactive_account", client)

        if password_needs_rehash(user.password_hash):
            self.users.set_password_hash(user, hash_password(password))
        self.users.record_successful_login(user, now=now)
        token = create_access_token(user.id, self.settings, now=now)
        self.audit.record(
            action="LOGIN_SUCCEEDED",
            actor_type=AuditActorType.USER,
            user_id=user.id,
            entity_type="user",
            entity_id=user.id,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
        )
        self.session.commit()
        logger.info("Login succeeded", extra={"user_id": str(user.id)})
        return user, token

    def _limited_network(self, client: ClientInfo) -> str | None:
        """The client's network for the per-network limit, or None when the limit is off or
        the address is unknown (unknown addresses are never pooled together)."""
        if not self.settings.LOGIN_PREFIX_LIMIT_ENABLED:
            return None
        return truncate_ip_address(client.ip_address)

    def _network_failures(self, network: str, now: datetime) -> int:
        return self.audit.count_for_network(network, "LOGIN_FAILED", since=now - NETWORK_WINDOW)

    def _fail(self, user: User | None, reason: str, client: ClientInfo):
        """Audit the failure (with its real reason), commit, and raise the generic error."""
        self.audit.record(
            action="LOGIN_FAILED",
            actor_type=AuditActorType.ANONYMOUS,
            user_id=user.id if user else None,
            entity_type="user" if user else None,
            entity_id=user.id if user else None,
            metadata={"reason": reason},
            ip_address=client.ip_address,
            user_agent=client.user_agent,
        )
        self.session.commit()
        logger.info("Login failed", extra={"reason": reason, "user_id": str(user.id) if user else None})
        raise InvalidCredentialsError()

    def _record_lockout(self, user: User, client: ClientInfo) -> None:
        minutes = self.settings.LOGIN_LOCKOUT_MINUTES
        self.audit.record(
            action="ACCOUNT_LOCKED",
            actor_type=AuditActorType.SYSTEM,
            user_id=user.id,
            entity_type="user",
            entity_id=user.id,
            metadata={"failed_attempts": self.settings.LOGIN_MAX_FAILED_ATTEMPTS, "lockout_minutes": minutes},
            ip_address=client.ip_address,
            user_agent=client.user_agent,
        )
        self.alerts.create(
            user_id=user.id,
            alert_type=AlertType.ACCOUNT_LOCKED,
            severity=AlertSeverity.CRITICAL,
            title="Sign-in temporarily locked",
            message=(
                f"{self.settings.LOGIN_MAX_FAILED_ATTEMPTS} incorrect passwords were entered for your account, "
                f"so sign-in was locked for {minutes} minutes. If this was not you, change your password."
            ),
        )
