"""Feature extraction service (P-1): the only part of the risk pipeline that reads the database.

Loads the user's earlier transactions around one payment and hands plain values to
the pure ``compute_features``. Read-only: it never writes and never commits.

Device history is derived from earlier APPROVED transactions' device hashes (P-1 D11:
no separate table). R6's dormant clause reads lifetime approved payments; every
other baseline uses the 90-day history.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.fraud_detection.config import RISK_CONFIG, RiskConfig
from app.fraud_detection.features import Features, PaymentContext, compute_features
from app.models import Beneficiary, Transaction, User
from app.repositories import TransactionRepository


class FeatureExtractor:
    def __init__(self, session: Session, config: RiskConfig = RISK_CONFIG) -> None:
        self.transactions = TransactionRepository(session)
        self.config = config

    def build(self, transaction: Transaction, *, beneficiary: Beneficiary, user: User) -> Features:
        config, at = self.config, transaction.initiated_at
        lifetime_count, lifetime_p90 = self.transactions.approved_amount_stats(
            transaction, percentile=config.dormant_percentile
        )
        context = PaymentContext(
            amount_paise=transaction.amount_paise,
            at=at,
            beneficiary_created_at=beneficiary.created_at,
            beneficiary_has_approved_payment=self.transactions.has_approved_payment_to_beneficiary(transaction),
            device_seen_before=self.transactions.device_seen(
                transaction, since=at - timedelta(days=config.device_history_days)
            ),
            last_login_at=user.last_login_at,
            approved_history=self.transactions.approved_history(
                transaction, since=at - timedelta(days=config.history_days)
            ),
            last_approved_at=self.transactions.last_approved_at(transaction),
            lifetime_approved_count=lifetime_count,
            lifetime_p90_paise=lifetime_p90,
            attempts_in_velocity_window=self.transactions.count_attempts(
                transaction, since=at - timedelta(minutes=config.velocity_window_minutes)
            ),
            approved_paise_in_daily_window=self.transactions.sum_approved_amount(
                transaction, since=at - timedelta(hours=config.daily_total_window_hours)
            ),
            repeat_attempt_in_window=self.transactions.has_repeat_attempt(
                transaction, since=at - timedelta(minutes=config.repeat_window_minutes)
            ),
        )
        return compute_features(context, config)
