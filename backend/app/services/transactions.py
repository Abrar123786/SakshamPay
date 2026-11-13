"""Transaction service (P-1, P-10): the only code that changes a transaction's status.

Simulated payments only: "approved" means approved in the simulation. No money moves.

Database transactions (the service owns them; repositories only flush):

  create_and_assess
    0. stale-state sweep                                          -> commit (own transaction)
    1. per-user creation lock (first statement), idempotency
       check, initiated_at = clock_timestamp(), insert INITIATED
       + audit                                                    -> commit (releases the lock)
    2. lock the row, extract features, assess, store the assessment,
       INITIATED -> ANALYSED -> AWAITING_USER_ACTION, audit rows,
       alert                                                      -> commit (all or nothing)
       on any failure: roll back step 2, then
    3. lock the row, INITIATED -> FAILED, audit, alert            -> commit

  apply_action
    lock the row, check expiry / state / allowed actions, change the status,
    audit, alert                                                  -> commit

Fail-closed: APPROVED is reachable only from AWAITING_USER_ACTION, which exists only
after a stored assessment, and only through an explicit CONTINUE or a successful
VERIFY. The repository state machine and the database constraints enforce the same.

Row locks (SELECT ... FOR UPDATE) plus the version column make concurrent requests
for one transaction run one after another. Lock order is always transaction, then
user, then the network lock (VERIFY only).

Velocity under concurrency (R3): step 1 holds a transaction-scoped advisory lock per
user and takes ``initiated_at`` from the database clock while holding it. Creation
transactions of one user therefore commit in ``initiated_at`` order, so when a
payment is assessed in step 2 every earlier attempt is already committed and visible:
the n-th attempt always counts n-1 earlier ones. The lock covers step 1 only (a few
milliseconds), never the assessment, and other users never wait for it.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import verify_password
from app.fraud_detection.config import RISK_CONFIG, RiskConfig
from app.fraud_detection.engine import Assessment, assess
from app.fraud_detection.ml import AnomalyScorer, UnavailableScorer
from app.fraud_detection.rules import format_inr
from app.models import (
    AlertSeverity,
    AlertType,
    ApprovalMethod,
    AuditActorType,
    RiskLevel,
    Transaction,
    TransactionStatus,
    User,
)
from app.models.enums import TERMINAL_TRANSACTION_STATUSES
from app.models.transaction import MAX_VERIFY_ATTEMPTS
from app.repositories import (
    AlertRepository,
    AuditLogRepository,
    BeneficiaryRepository,
    RiskAssessmentRepository,
    TransactionRepository,
    UserRepository,
)
from app.repositories.errors import IdempotencyKeyReusedError, InvalidStateTransitionError
from app.repositories.locks import CREATE_PAYMENT, VERIFY_PREFIX, advisory_xact_lock
from app.schemas.transactions import ActionRequest, TransactionCreate, TransactionOut, transaction_view
from app.services.auth import ClientInfo
from app.services.errors import (
    ActionNotAllowedError,
    AmountOutOfRangeError,
    ConfirmationRequiredError,
    StepUpRequiredError,
    TooManyVerificationAttemptsError,
    TransactionExpiredError,
    VerificationFailedError,
)
from app.services.feature_extraction import FeatureExtractor
from app.utils.privacy import hash_device_id, identifier_key, truncate_ip_address

logger = logging.getLogger("sakshampay.transactions")

S = TransactionStatus
SWEEP_BATCH = 50

NOTHING_PAID = "Nothing was paid."


@dataclass(frozen=True)
class CreateOutcome:
    transaction: TransactionOut
    created: bool  # False: the Idempotency-Key was already used and the stored payment is returned


class TransactionService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        scorer: AnomalyScorer | None = None,
        config: RiskConfig = RISK_CONFIG,
    ) -> None:
        self.session = session
        self.settings = settings
        self.config = config
        self.scorer: AnomalyScorer = scorer or UnavailableScorer()
        self.transactions = TransactionRepository(session)
        self.assessments = RiskAssessmentRepository(session)
        self.beneficiaries = BeneficiaryRepository(session)
        self.users = UserRepository(session)
        self.alerts = AlertRepository(session)
        self.audit = AuditLogRepository(session)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    # ---- create and assess ------------------------------------------------------------------------

    def create_and_assess(
        self, user: User, request: TransactionCreate, *, idempotency_key: str, device_id: str, client: ClientInfo
    ) -> CreateOutcome:
        user_id = user.id
        self._sweep(self._now())  # (0) its own database transaction, before any lock

        request_hash = request.request_hash()
        # (1) First statement of the creation transaction: no other lock is held yet.
        advisory_xact_lock(self.session, CREATE_PAYMENT, str(user_id))
        existing = self.transactions.get_by_idempotency_key(user_id, idempotency_key)  # re-checked under the lock
        if existing is not None:
            self.session.rollback()  # release the creation lock before waiting on the stored payment
            return self._replay(existing, request_hash, user_id)

        if request.amount_paise > self.settings.MAX_TRANSACTION_AMOUNT_PAISE:
            raise AmountOutOfRangeError(
                f"The most you can send in one simulated payment is {format_inr(self.settings.MAX_TRANSACTION_AMOUNT_PAISE)}."
            )
        self.beneficiaries.require_for_user(request.beneficiary_id, user_id)  # active and owned, else 404
        device_hash = hash_device_id(device_id, identifier_key(self.settings))
        # Database clock, read under the lock: one user's attempts get increasing times in commit order.
        initiated_at = self.session.scalar(select(func.clock_timestamp()))

        result = self.transactions.create_idempotent(
            user_id=user_id,
            beneficiary_id=request.beneficiary_id,
            amount_paise=request.amount_paise,
            transaction_type=request.transaction_type,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            description=request.description,
            device_id_hash=device_hash,
            initiated_at=initiated_at,
        )
        if not result.created:  # backstop only: the lock already serialises same-key requests
            self.session.rollback()
            return self._replay(result.transaction, request_hash, user_id)

        transaction_id = result.transaction.id
        self.audit.record(
            action="TRANSACTION_INITIATED",
            actor_type=AuditActorType.USER,
            user_id=user_id,
            transaction_id=transaction_id,
            entity_type="transaction",
            entity_id=transaction_id,
            new_values={"status": S.INITIATED.value, "amount_paise": request.amount_paise},
            ip_address=client.ip_address,
            user_agent=client.user_agent,
        )
        self.session.commit()  # (1) the attempt is durable before it is assessed; releases the lock

        started = time.perf_counter()
        result: Assessment | None = None
        try:
            result = self._assess(transaction_id, user_id)  # (2)
        except Exception as error:  # noqa: BLE001 - every assessment failure ends in FAILED, never in approval
            self.session.rollback()
            logger.exception("Assessment failed; marking the transaction FAILED", extra={"error_type": type(error).__name__})
            self._fail_after_error(transaction_id, user_id, error)  # (3)
        view = self._view(self.transactions.require_for_user(transaction_id, user_id))
        # P-1 observability: one structured line per assessment (request_id is added by the
        # logging setup). No amount, payee, device or feature values.
        logger.info(
            "Payment assessed",
            extra={
                "transaction_id": str(transaction_id),
                "assessment_ms": round((time.perf_counter() - started) * 1000, 1),
                "ml_available": result.ml_available if result else None,
                "risk_level": result.risk_level.value if result else None,
                "outcome": view.status.value,
            },
        )
        return CreateOutcome(view, created=True)

    def _replay(self, existing: Transaction, request_hash: str, user_id: uuid.UUID) -> CreateOutcome:
        if existing.request_hash != request_hash:
            raise IdempotencyKeyReusedError()
        if existing.status == S.INITIATED:
            # The original request may still be assessing it: wait for its row lock so the
            # replay returns the finished result where possible.
            try:
                self.transactions.get_for_update(existing.id, user_id)
            except DBAPIError:  # lock wait exceeded the statement timeout
                pass
            self.session.rollback()  # release the lock; nothing was changed
            existing = self.transactions.require_for_user(existing.id, user_id)
        return CreateOutcome(self._view(self._settle(existing, user_id)), created=False)

    def _assess(self, transaction_id: uuid.UUID, user_id: uuid.UUID) -> Assessment | None:
        transaction = self.transactions.get_for_update(transaction_id, user_id)
        if transaction.status != S.INITIATED:
            self.session.rollback()
            return None
        at = max(self._now(), transaction.initiated_at)
        user = self.users.get(user_id)
        beneficiary = self.beneficiaries.get_for_user(transaction.beneficiary_id, user_id, include_inactive=True)
        features = FeatureExtractor(self.session, self.config).build(transaction, beneficiary=beneficiary, user=user)
        result: Assessment = assess(features, scorer=self.scorer, now=at, config=self.config)

        stored = self.assessments.create(
            transaction,
            rule_score=result.rule_score,
            ml_score=result.ml_score,
            risk_level=result.risk_level,
            config_version=result.config_version,
            model_version=result.model_version,
            rule_details=result.rule_details,
            ml_details=result.ml_details,
            explanation=result.factors,
            features_snapshot=result.features_snapshot,
            allowed_actions=result.decision.allowed_actions,
            assessed_at=at,
        )
        self.transactions.transition(transaction, S.ANALYSED, at=at)
        self._audit_system(
            "TRANSACTION_ASSESSED",
            transaction,
            old={"status": S.INITIATED.value},
            new={
                "status": S.ANALYSED.value,
                "rule_score": stored.rule_score,
                "ml_score": stored.ml_score,
                "final_risk_score": stored.final_risk_score,
                "risk_level": stored.risk_level.value,
            },
            metadata={"config_version": result.config_version, "model_version": result.model_version, "ml_available": result.ml_available},
        )
        self.transactions.transition(transaction, S.AWAITING_USER_ACTION, at=at, expires_at=result.decision.expires_at)
        self._audit_system(
            "TRANSACTION_AWAITING_ACTION",
            transaction,
            old={"status": S.ANALYSED.value},
            new={
                "status": S.AWAITING_USER_ACTION.value,
                "allowed_actions": result.decision.allowed_actions,
                "recommended_action": result.decision.recommended_action,
                "expires_at": result.decision.expires_at.isoformat(),
            },
        )
        if not result.ml_available:
            self._audit_system(
                "ML_UNAVAILABLE", transaction, metadata={"reason": result.ml_unavailable_reason, "mode": "rules_only"}
            )
        if result.risk_level != RiskLevel.LOW:
            labels = [factor["label"] for factor in result.factors if factor["source"] == "rule"]
            self.alerts.create(
                user_id=user_id,
                transaction_id=transaction.id,
                risk_assessment_id=stored.id,
                alert_type=AlertType.RISK_WARNING,
                severity=AlertSeverity.CRITICAL if result.risk_level == RiskLevel.HIGH else AlertSeverity.WARNING,
                title=f"{result.risk_level.value.capitalize()}-risk payment of {format_inr(transaction.amount_paise)}",
                message=("; ".join(labels) or "Review this payment before continuing.")[:500],
            )
        self.session.commit()
        return result

    def _fail_after_error(self, transaction_id: uuid.UUID, user_id: uuid.UUID, error: Exception) -> None:
        transaction = self.transactions.get_for_update(transaction_id, user_id)
        if transaction.status == S.INITIATED:
            self._fail(transaction, self._now(), reason="assessment_error", error_type=type(error).__name__)
        self.session.commit()

    # ---- read ----------------------------------------------------------------------------------------

    def get(self, user: User, transaction_id: uuid.UUID) -> TransactionOut:
        transaction = self.transactions.require_for_user(transaction_id, user.id)
        return self._view(self._settle(transaction, user.id))

    # ---- user action ---------------------------------------------------------------------------------

    def apply_action(self, user: User, transaction_id: uuid.UUID, request: ActionRequest, *, client: ClientInfo) -> TransactionOut:
        now = self._now()
        user_id = user.id
        transaction = self.transactions.get_for_update(transaction_id, user_id)  # 404 unless it is the user's

        if transaction.status == S.AWAITING_USER_ACTION and transaction.expires_at < now:
            self._expire(transaction, now)
            self.session.commit()
            raise TransactionExpiredError()

        if transaction.status in TERMINAL_TRANSACTION_STATUSES:
            if self._already_done(transaction, request.action):
                self.session.rollback()  # release the lock; repeating the same action changes nothing
                return self._view(self.transactions.require_for_user(transaction_id, user_id))
            if transaction.status == S.EXPIRED:
                # The same answer whichever request expired it (this one, an earlier read or the sweep).
                raise TransactionExpiredError()
            raise InvalidStateTransitionError("This payment is already finished and cannot be changed.")
        if transaction.status != S.AWAITING_USER_ACTION:
            raise InvalidStateTransitionError("This payment is still being assessed.")

        assessment = self.assessments.get_by_transaction(transaction.id)
        allowed = assessment.allowed_actions

        if request.action == "CANCEL":
            if "CANCEL" not in allowed:
                raise ActionNotAllowedError()
            self._cancel(transaction, now, actor=AuditActorType.USER, reason="user_cancelled", client=client)
            self.alerts.create(
                user_id=user_id,
                transaction_id=transaction.id,
                alert_type=AlertType.TRANSACTION_CANCELLED,
                severity=AlertSeverity.INFO,
                title="Payment cancelled",
                message=f"Your simulated payment of {format_inr(transaction.amount_paise)} was cancelled. {NOTHING_PAID}",
            )
        elif request.action == "CONTINUE":
            if "CONTINUE" not in allowed:
                raise StepUpRequiredError()
            if assessment.risk_level == RiskLevel.MEDIUM and request.confirmed is not True:
                raise ConfirmationRequiredError()
            self._approve(transaction, now, ApprovalMethod.CONTINUE, client)
        else:  # VERIFY
            if "VERIFY" not in allowed:
                raise ActionNotAllowedError("Verification is not needed for this payment.")
            self._verify(transaction, user_id, request, now, client)

        self.session.commit()
        return self._view(transaction)

    @staticmethod
    def _already_done(transaction: Transaction, action: str) -> bool:
        """P-1: repeating the action that produced the current state returns that state."""
        if action == "CANCEL":
            return transaction.status == S.CANCELLED
        method = ApprovalMethod.CONTINUE if action == "CONTINUE" else ApprovalMethod.VERIFIED
        return transaction.status == S.APPROVED and transaction.approval_method == method

    def _verify(self, transaction: Transaction, user_id: uuid.UUID, request: ActionRequest, now: datetime, client: ClientInfo) -> None:
        user = self.users.get_for_update(user_id)  # one verification at a time per user
        since = now - self.config.verify_failure_window
        if self.audit.count_for_user(user_id, "VERIFICATION_FAILED", since=since) >= self.config.verify_failure_limit:
            raise TooManyVerificationAttemptsError()

        network = self._limited_network(client)
        if network and self._network_failures(network, since) >= self.settings.VERIFY_PREFIX_FAILURE_LIMIT:
            raise TooManyVerificationAttemptsError()  # cheap early answer; the locked check below decides

        correct = verify_password(user.password_hash, request.password.get_secret_value())  # no network lock held

        if network:
            # Count and record under one per-network lock, so concurrent failures from
            # different accounts on this network are counted exactly. Over the limit,
            # even a correct password is refused (otherwise the limit would leak whether
            # a guess was right), and nothing is recorded.
            advisory_xact_lock(self.session, VERIFY_PREFIX, network)
            if self._network_failures(network, since) >= self.settings.VERIFY_PREFIX_FAILURE_LIMIT:
                raise TooManyVerificationAttemptsError()

        if correct:
            self._approve(transaction, now, ApprovalMethod.VERIFIED, client)
            return

        attempts = self.transactions.record_failed_verification(transaction)
        remaining = MAX_VERIFY_ATTEMPTS - attempts
        self.audit.record(
            action="VERIFICATION_FAILED",
            actor_type=AuditActorType.USER,
            user_id=user_id,
            transaction_id=transaction.id,
            entity_type="transaction",
            entity_id=transaction.id,
            metadata={"attempt": attempts, "attempts_remaining": remaining},
            ip_address=client.ip_address,
            user_agent=client.user_agent,
        )
        if remaining == 0:
            self._cancel(transaction, now, actor=AuditActorType.SYSTEM, reason="verification_failed", client=None)
            self.alerts.create(
                user_id=user_id,
                transaction_id=transaction.id,
                alert_type=AlertType.VERIFICATION_FAILED,
                severity=AlertSeverity.WARNING,
                title="Payment cancelled after failed verification",
                message=(
                    f"Verification failed {MAX_VERIFY_ATTEMPTS} times, so your simulated payment of "
                    f"{format_inr(transaction.amount_paise)} was cancelled. {NOTHING_PAID}"
                ),
            )
        self.session.commit()  # the failed attempt must be kept even though the request is rejected
        raise VerificationFailedError(context={"attempts_remaining": remaining, "status": transaction.status.value})

    def _limited_network(self, client: ClientInfo) -> str | None:
        """The client's network for the per-network Verify limit, or None when the limit is
        off or the address is unknown (unknown addresses are never pooled together)."""
        if not self.settings.VERIFY_PREFIX_LIMIT_ENABLED:
            return None
        return truncate_ip_address(client.ip_address)

    def _network_failures(self, network: str, since: datetime) -> int:
        return self.audit.count_for_network(network, "VERIFICATION_FAILED", since=since)

    # ---- status changes (the only callers of TransactionRepository.transition) --------------------

    def _approve(self, transaction: Transaction, now: datetime, method: ApprovalMethod, client: ClientInfo) -> None:
        self.transactions.transition(transaction, S.APPROVED, at=self._after(transaction, now), approval_method=method)
        self.audit.record(
            action="TRANSACTION_APPROVED",
            actor_type=AuditActorType.USER,
            user_id=transaction.user_id,
            transaction_id=transaction.id,
            entity_type="transaction",
            entity_id=transaction.id,
            old_values={"status": S.AWAITING_USER_ACTION.value},
            new_values={"status": S.APPROVED.value, "approval_method": method.value},
            metadata={"simulated": True},
            ip_address=client.ip_address,
            user_agent=client.user_agent,
        )

    def _cancel(self, transaction: Transaction, now: datetime, *, actor: AuditActorType, reason: str, client: ClientInfo | None) -> None:
        self.transactions.transition(transaction, S.CANCELLED, at=self._after(transaction, now))
        self.audit.record(
            action="TRANSACTION_CANCELLED",
            actor_type=actor,
            user_id=transaction.user_id,
            transaction_id=transaction.id,
            entity_type="transaction",
            entity_id=transaction.id,
            old_values={"status": S.AWAITING_USER_ACTION.value},
            new_values={"status": S.CANCELLED.value, "reason": reason},
            ip_address=client.ip_address if client else None,
            user_agent=client.user_agent if client else None,
        )

    def _expire(self, transaction: Transaction, now: datetime) -> None:
        self.transactions.transition(transaction, S.EXPIRED, at=self._after(transaction, now))
        self._audit_system(
            "TRANSACTION_EXPIRED", transaction, old={"status": S.AWAITING_USER_ACTION.value}, new={"status": S.EXPIRED.value}
        )
        minutes = int(self.config.decision_window.total_seconds() // 60)
        self.alerts.create(
            user_id=transaction.user_id,
            transaction_id=transaction.id,
            alert_type=AlertType.TRANSACTION_EXPIRED,
            severity=AlertSeverity.INFO,
            title="Payment expired",
            message=f"No action was taken within {minutes} minutes, so the simulated payment was not sent. {NOTHING_PAID}",
        )

    def _fail(self, transaction: Transaction, now: datetime, *, reason: str, error_type: str | None = None) -> None:
        self.transactions.transition(transaction, S.FAILED, at=self._after(transaction, now))
        self._audit_system(
            "TRANSACTION_FAILED",
            transaction,
            old={"status": S.INITIATED.value},
            new={"status": S.FAILED.value, "reason": reason},
            metadata={"error_type": error_type} if error_type else None,
        )
        self.alerts.create(
            user_id=transaction.user_id,
            transaction_id=transaction.id,
            alert_type=AlertType.TRANSACTION_FAILED,
            severity=AlertSeverity.INFO,
            title="Payment not sent",
            message=f"We could not assess this payment, so it was not sent. {NOTHING_PAID}",
        )

    @staticmethod
    def _after(transaction: Transaction, now: datetime) -> datetime:
        """Never earlier than the transaction's own earlier timestamps (the database checks their order)."""
        return max(now, transaction.analysed_at or transaction.initiated_at)

    # ---- expiry and stale attempts -----------------------------------------------------------------

    def _is_overdue(self, transaction: Transaction, now: datetime) -> bool:
        if transaction.status == S.AWAITING_USER_ACTION:
            return transaction.expires_at < now
        return transaction.status == S.INITIATED and transaction.initiated_at < now - self.config.stale_initiated_after

    def _settle(self, transaction: Transaction, user_id: uuid.UUID) -> Transaction:
        """Lazy expiry (P-1): on a read, a payment past its deadline becomes EXPIRED and an
        attempt abandoned mid-assessment becomes FAILED."""
        now = self._now()
        if not self._is_overdue(transaction, now):
            return transaction
        transaction = self.transactions.get_for_update(transaction.id, user_id)
        if self._is_overdue(transaction, now):  # re-checked under the lock
            if transaction.status == S.AWAITING_USER_ACTION:
                self._expire(transaction, now)
            else:
                self._fail(transaction, now, reason="assessment_abandoned")
        self.session.commit()
        return transaction

    def _sweep(self, now: datetime) -> None:
        """Best effort, bounded, all users (P-1 stale-state sweep). Rows locked by another
        request are skipped; a sweep failure never blocks the request that triggered it."""
        try:
            for transaction in self.transactions.lock_expired_awaiting(now, limit=SWEEP_BATCH):
                self._expire(transaction, now)
            stale_before = now - self.config.stale_initiated_after
            for transaction in self.transactions.lock_stale_initiated(stale_before, limit=SWEEP_BATCH):
                self._fail(transaction, now, reason="assessment_abandoned")
            self.session.commit()
        except Exception:  # noqa: BLE001
            self.session.rollback()
            logger.warning("Stale-state sweep failed; continuing", exc_info=True)

    # ---- helpers ---------------------------------------------------------------------------------------

    def _audit_system(self, action: str, transaction: Transaction, *, old: dict | None = None, new: dict | None = None, metadata: dict | None = None) -> None:
        self.audit.record(
            action=action,
            actor_type=AuditActorType.SYSTEM,
            user_id=transaction.user_id,
            transaction_id=transaction.id,
            entity_type="transaction",
            entity_id=transaction.id,
            old_values=old,
            new_values=new,
            metadata=metadata,
        )

    def _view(self, transaction: Transaction) -> TransactionOut:
        beneficiary = self.beneficiaries.get_for_user(transaction.beneficiary_id, transaction.user_id, include_inactive=True)
        assessment = self.assessments.get_by_transaction(transaction.id)
        return transaction_view(transaction, beneficiary, assessment, now=self._now(), config=self.config)
