"""Dashboard queries (P-1 "Dashboard queries, read-only"; P-9).

Read-only by construction: the service must be given a session from
``get_read_only_db``, whose transaction is REPEATABLE READ, READ ONLY from its
first statement, so PostgreSQL itself rejects any write and every figure comes
from one snapshot. The service checks this and never commits. Transactions are
counted in their stored state; nothing is expired or otherwise changed here (the
expiry sweep belongs to the transaction service).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import TransactionStatus
from app.repositories import AlertRepository, TransactionRepository
from app.schemas.dashboard import (
    DashboardAlerts,
    DashboardPeriod,
    DashboardSummary,
    DashboardTransactions,
    TransactionStatusCounts,
)

WINDOW_DAYS = 30


class NotReadOnlySessionError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("DashboardService needs a read-only session (app.database.session.get_read_only_db).")


class DashboardService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.transactions = TransactionRepository(session)
        self.alerts = AlertRepository(session)

    def summary(self, user_id: uuid.UUID, *, now: datetime | None = None) -> DashboardSummary:
        """Figures for one user over the rolling window [now - 30 days, now] on created_at."""
        end = now or datetime.now(UTC)
        start = end - timedelta(days=WINDOW_DAYS)

        # Refuse to run on an ordinary read-write session: the read-only guarantee
        # must come from the transaction itself, not from this code being careful.
        if self.session.scalar(text("SHOW transaction_read_only")) != "on":
            raise NotReadOnlySessionError()

        by_status = self.transactions.count_by_status(user_id, start=start, end=end)
        return DashboardSummary(
            period=DashboardPeriod(days=WINDOW_DAYS, start=start, end=end),
            transactions=DashboardTransactions(
                total=sum(by_status.values()),
                by_status=TransactionStatusCounts(**{status.value: count for status, count in by_status.items()}),
                awaiting_action=self.transactions.count_awaiting_action(user_id, now=end, start=start, end=end),
                approved_amount_paise=self.transactions.sum_amount(
                    user_id, status=TransactionStatus.APPROVED, start=start, end=end
                ),
            ),
            alerts=DashboardAlerts(unread=self.alerts.count_unread(user_id)),
        )
