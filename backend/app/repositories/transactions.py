import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import (
    ApprovalMethod,
    RiskAssessment,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from app.models.enums import TERMINAL_TRANSACTION_STATUSES
from app.models.transaction import MAX_VERIFY_ATTEMPTS
from app.repositories.base import Repository, clamp_limit, clamp_offset, violated_constraint
from app.repositories.errors import (
    BeneficiaryNotFoundError,
    IdempotencyKeyReusedError,
    InvalidStateTransitionError,
    TransactionNotFoundError,
)

S = TransactionStatus

# P-1 lifecycle. Verification failures below the limit keep AWAITING_USER_ACTION
# (see record_failed_verification); terminal states have no exits.
ALLOWED_TRANSITIONS: dict[TransactionStatus, frozenset[TransactionStatus]] = {
    S.INITIATED: frozenset({S.ANALYSED, S.FAILED}),
    S.ANALYSED: frozenset({S.AWAITING_USER_ACTION}),
    S.AWAITING_USER_ACTION: frozenset({S.APPROVED, S.CANCELLED, S.EXPIRED}),
    S.APPROVED: frozenset(),
    S.CANCELLED: frozenset(),
    S.EXPIRED: frozenset(),
    S.FAILED: frozenset(),
}

# Which stored allowed_action an approval method needs (P-1 decision engine).
_REQUIRED_ACTION = {ApprovalMethod.CONTINUE: "CONTINUE", ApprovalMethod.VERIFIED: "VERIFY"}


@dataclass(frozen=True)
class CreateResult:
    transaction: Transaction
    created: bool  # False: an earlier request with the same Idempotency-Key is being replayed


def _now() -> datetime:
    return datetime.now(UTC)


class TransactionRepository(Repository):
    """Simulated payment records and their P-1 lifecycle.

    * Creation is idempotent per (user, Idempotency-Key), including under concurrency.
    * Status changes go through ``transition`` only, which enforces the P-1 state
      machine and sets the matching timestamps.
    * ``version`` (optimistic locking) makes a stale write fail with
      ConcurrentModificationError; ``get_for_update`` takes a row lock when a
      read-then-write must not interleave with another request.
    * There is no delete.
    """

    # ---- create -------------------------------------------------------------------

    def create_idempotent(
        self,
        *,
        user_id: uuid.UUID,
        beneficiary_id: uuid.UUID,
        amount_paise: int,
        transaction_type: TransactionType,
        idempotency_key: str,
        request_hash: str,
        description: str | None = None,
        device_id_hash: str | None = None,
        initiated_at: datetime | None = None,
    ) -> CreateResult:
        """Insert a new INITIATED transaction, or return the one already created with this key.

        The same key with a different ``request_hash`` raises IdempotencyKeyReusedError.
        ``initiated_at`` is for imports and seed data; normally the database clock is used.
        """
        existing = self.get_by_idempotency_key(user_id, idempotency_key)
        if existing is not None:
            return self._replay(existing, request_hash)

        transaction = Transaction(
            user_id=user_id,
            beneficiary_id=beneficiary_id,
            amount_paise=amount_paise,
            transaction_type=transaction_type,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            description=description,
            device_id_hash=device_id_hash,
        )
        if initiated_at is not None:
            transaction.initiated_at = initiated_at
            transaction.created_at = initiated_at
        try:
            # Ownership FK: the beneficiary must belong to this user.
            self.add(transaction, {"fk_transactions_beneficiary_id_user_id_beneficiaries": BeneficiaryNotFoundError})
        except IntegrityError as exc:
            if violated_constraint(exc) != "uq_transactions_user_id_idempotency_key":
                raise
            # A concurrent request with the same key committed first: replay it.
            existing = self.get_by_idempotency_key(user_id, idempotency_key)
            if existing is None:  # pragma: no cover - the unique violation proves it exists
                raise
            return self._replay(existing, request_hash)
        return CreateResult(transaction=transaction, created=True)

    @staticmethod
    def _replay(existing: Transaction, request_hash: str) -> CreateResult:
        if existing.request_hash != request_hash:
            raise IdempotencyKeyReusedError()
        return CreateResult(transaction=existing, created=False)

    # ---- reads (always scoped to the owner unless marked as system use) -------------

    def get_for_user(self, transaction_id: uuid.UUID, user_id: uuid.UUID) -> Transaction | None:
        return self.session.scalar(
            select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user_id)
        )

    def require_for_user(self, transaction_id: uuid.UUID, user_id: uuid.UUID) -> Transaction:
        transaction = self.get_for_user(transaction_id, user_id)
        if transaction is None:
            raise TransactionNotFoundError()
        return transaction

    def get_for_update(self, transaction_id: uuid.UUID, user_id: uuid.UUID) -> Transaction:
        """Owner-scoped read with SELECT ... FOR UPDATE: concurrent writers wait for this one."""
        transaction = self.session.scalar(
            select(Transaction)
            .where(Transaction.id == transaction_id, Transaction.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if transaction is None:
            raise TransactionNotFoundError()
        return transaction

    def get_by_idempotency_key(self, user_id: uuid.UUID, idempotency_key: str) -> Transaction | None:
        return self.session.scalar(
            select(Transaction).where(
                Transaction.user_id == user_id, Transaction.idempotency_key == idempotency_key
            )
        )

    def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        statuses: Iterable[TransactionStatus] | None = None,
        beneficiary_id: uuid.UUID | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Transaction]:
        query = select(Transaction).where(Transaction.user_id == user_id)
        if statuses:
            query = query.where(Transaction.status.in_(list(statuses)))
        if beneficiary_id is not None:
            query = query.where(Transaction.beneficiary_id == beneficiary_id)
        query = (
            query.order_by(Transaction.created_at.desc(), Transaction.id)
            .limit(clamp_limit(limit))
            .offset(clamp_offset(offset))
        )
        return list(self.session.scalars(query))

    def list_by_status(self, status: TransactionStatus, *, limit: int | None = None) -> list[Transaction]:
        """System use (sweeps, monitoring): all users, oldest first."""
        query = (
            select(Transaction)
            .where(Transaction.status == status)
            .order_by(Transaction.created_at, Transaction.id)
            .limit(clamp_limit(limit))
        )
        return list(self.session.scalars(query))

    def list_expired_awaiting(self, now: datetime, *, limit: int | None = None) -> list[Transaction]:
        """System use: AWAITING_USER_ACTION past its deadline (uses the partial index)."""
        query = (
            select(Transaction)
            .where(Transaction.status == S.AWAITING_USER_ACTION, Transaction.expires_at < now)
            .order_by(Transaction.expires_at)
            .limit(clamp_limit(limit))
        )
        return list(self.session.scalars(query))

    def list_stale_initiated(self, older_than: datetime, *, limit: int | None = None) -> list[Transaction]:
        """System use: INITIATED rows abandoned mid-assessment (uses the partial index)."""
        query = (
            select(Transaction)
            .where(Transaction.status == S.INITIATED, Transaction.initiated_at < older_than)
            .order_by(Transaction.initiated_at)
            .limit(clamp_limit(limit))
        )
        return list(self.session.scalars(query))

    # ---- aggregates (read-only, one user, a created_at window) ------------------------
    # The window is start <= created_at <= end; it uses ix_transactions_user_id_created_at.

    def _in_window(self, user_id: uuid.UUID, start: datetime, end: datetime):
        return (Transaction.user_id == user_id, Transaction.created_at >= start, Transaction.created_at <= end)

    def count_by_status(self, user_id: uuid.UUID, *, start: datetime, end: datetime) -> dict[TransactionStatus, int]:
        """Stored status of each of the user's transactions in the window. Every status is present (0 if none)."""
        rows = self.session.execute(
            select(Transaction.status, func.count())
            .where(*self._in_window(user_id, start, end))
            .group_by(Transaction.status)
        )
        counts = {status: 0 for status in TransactionStatus}
        for status, count in rows:
            counts[TransactionStatus(status)] = count
        return counts

    def sum_amount(self, user_id: uuid.UUID, *, status: TransactionStatus, start: datetime, end: datetime) -> int:
        """Total amount_paise of the user's transactions with this status in the window (0 if none)."""
        total = self.session.scalar(
            select(func.coalesce(func.sum(Transaction.amount_paise), 0)).where(
                *self._in_window(user_id, start, end), Transaction.status == status
            )
        )
        return int(total)

    def count_awaiting_action(self, user_id: uuid.UUID, *, now: datetime, start: datetime, end: datetime) -> int:
        """AWAITING_USER_ACTION whose decision window is still open (expires_at >= now).

        A row past expires_at that the sweep has not yet marked EXPIRED is not
        counted: the user can no longer act on it. Same boundary as list_expired_awaiting.
        """
        return self.session.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(
                *self._in_window(user_id, start, end),
                Transaction.status == S.AWAITING_USER_ACTION,
                Transaction.expires_at >= now,
            )
        )

    # ---- lifecycle --------------------------------------------------------------------

    def transition(
        self,
        transaction: Transaction,
        to_status: TransactionStatus,
        *,
        at: datetime | None = None,
        expires_at: datetime | None = None,
        approval_method: ApprovalMethod | None = None,
    ) -> Transaction:
        """Move to ``to_status`` if the P-1 lifecycle allows it, setting its timestamps.

        Guards beyond the database constraints:
          * ANALYSED requires a stored risk assessment;
          * AWAITING_USER_ACTION requires a future ``expires_at``;
          * APPROVED requires an ``approval_method`` that the stored assessment allowed
            (CONTINUE needs "CONTINUE", VERIFIED needs "VERIFY").
        """
        at = at or _now()
        current = transaction.status
        if to_status not in ALLOWED_TRANSITIONS[current]:
            raise InvalidStateTransitionError(f"Cannot move a transaction from {current} to {to_status}.")

        if to_status == S.ANALYSED and self._assessment_for(transaction) is None:
            raise InvalidStateTransitionError("A transaction can only be ANALYSED after its risk assessment is stored.")

        if to_status == S.AWAITING_USER_ACTION:
            if expires_at is None or expires_at <= at:
                raise InvalidStateTransitionError("AWAITING_USER_ACTION needs an expiry time in the future.")
            transaction.expires_at = expires_at

        if to_status == S.APPROVED:
            if approval_method is None:
                raise InvalidStateTransitionError("APPROVED needs an approval method.")
            assessment = self._assessment_for(transaction)
            required = _REQUIRED_ACTION[approval_method]
            if assessment is None or required not in assessment.allowed_actions:
                raise InvalidStateTransitionError(
                    f"The risk assessment does not allow approval by {approval_method}."
                )
            transaction.approval_method = approval_method
        elif approval_method is not None:
            raise InvalidStateTransitionError("Only APPROVED records an approval method.")

        if to_status == S.ANALYSED:
            transaction.analysed_at = at
        if to_status in TERMINAL_TRANSACTION_STATUSES:
            transaction.completed_at = at

        transaction.status = to_status
        self.flush()  # version check: a concurrent change raises ConcurrentModificationError
        return transaction

    def record_failed_verification(self, transaction: Transaction) -> int:
        """Count a failed step-up verification; returns attempts used. The caller cancels
        the transaction when the limit is reached (P-1)."""
        if transaction.status != S.AWAITING_USER_ACTION:
            raise InvalidStateTransitionError("Verification is only possible while awaiting user action.")
        if transaction.verify_attempts >= MAX_VERIFY_ATTEMPTS:
            raise InvalidStateTransitionError("No verification attempts remain.")
        transaction.verify_attempts += 1
        self.flush()
        return transaction.verify_attempts

    def _assessment_for(self, transaction: Transaction) -> RiskAssessment | None:
        return self.session.scalar(select(RiskAssessment).where(RiskAssessment.transaction_id == transaction.id))
