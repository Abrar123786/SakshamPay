"""Feature vector for one payment (P-1 "Features"), computed from plain values.

Pure functions: no database access. ``app.services.feature_extraction`` loads the
history and calls ``compute_features``. Only the features the rules use are built
here; the ML-only features (log_amount, hour_sin/cos, amount_z_user) arrive with
the model.

History means the user's APPROVED payments in the 90 days before this payment.
With fewer than ``cold_start_min_history`` of them the user is in cold start, and
only the cold-start values P-1 defines are used (R2 amount, R4 hours). Baselines
P-1 does not define for cold start stay ``None`` and the clauses that need them
are not evaluated.

One exception (approved for P-10): R6's dormant-account clause compares the payment
with the account's own 90th percentile, and a dormant account's own payments lie
before the idle gap, often outside the 90-day window. That clause therefore uses the
user's LIFETIME approved payments, with the same minimum of ``cold_start_min_history``
payments. It does not change cold start or any other baseline.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime

from app.fraud_detection.config import IST, RiskConfig


def percentile(values: Sequence[int], q: float) -> float:
    """q-th percentile (0-100) with linear interpolation: numpy.percentile's default."""
    if not values:
        raise ValueError("percentile of no values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


@dataclass(frozen=True)
class PaymentContext:
    """What is known about the payment being assessed and its surroundings."""

    amount_paise: int
    at: datetime  # when it was initiated (timezone-aware)
    beneficiary_created_at: datetime
    beneficiary_has_approved_payment: bool  # an earlier APPROVED payment to this beneficiary
    device_seen_before: bool  # same device hash on an earlier APPROVED payment in the device window
    last_login_at: datetime | None
    # Earlier APPROVED payments in the history window: (amount_paise, initiated_at).
    approved_history: Sequence[tuple[int, datetime]]
    last_approved_at: datetime | None  # the most recent APPROVED payment at any time
    lifetime_approved_count: int  # earlier APPROVED payments at any time (R6 dormant clause)
    lifetime_p90_paise: float | None  # their 90th percentile amount (None when there are none)
    attempts_in_velocity_window: int  # earlier attempts, any status
    approved_paise_in_daily_window: int  # earlier APPROVED amounts in the last 24 hours
    repeat_attempt_in_window: bool  # an earlier attempt, same beneficiary and amount


@dataclass(frozen=True)
class Features:
    amount_paise: int
    hour_ist: float  # 2.67 = 02:40 IST
    cold_start: bool
    history_count: int
    # Personal baselines (None in cold start).
    median_amount_paise: float | None
    amount_p95_paise: float | None
    dormant_p90_paise: float | None  # lifetime 90th percentile for R6's dormant clause (None below the minimum)
    lifetime_approved_count: int
    typical_daily_total_paise: float | None
    hour_share: float | None  # share of past payments made in this clock hour (IST)
    # Signals.
    is_unusual_hour: bool
    txn_count_10m: int  # earlier attempts in the velocity window
    amount_sum_24h_paise: int  # approved in the last 24 hours plus this payment
    amount_sum_24h_ratio: float | None
    repeat_same_payee_amount_5m: bool
    is_new_beneficiary: bool
    beneficiary_age_hours: float
    is_new_device: bool
    seconds_since_login: float | None
    days_since_last_txn: float | None

    def snapshot(self) -> dict:
        """JSON-safe copy stored with the assessment (never returned by the API)."""
        return {key: (round(value, 4) if isinstance(value, float) else value) for key, value in asdict(self).items()}


def _ist(at: datetime) -> datetime:
    if at.tzinfo is None:
        raise ValueError("feature timestamps must be timezone-aware")
    return at.astimezone(IST)


def _hour_ist(at: datetime) -> float:
    local = _ist(at)
    return local.hour + local.minute / 60 + local.second / 3600


def compute_features(context: PaymentContext, config: RiskConfig) -> Features:
    amounts = [amount for amount, _ in context.approved_history]
    cold_start = len(amounts) < config.cold_start_min_history
    hour = _hour_ist(context.at)

    median = p95 = typical_daily = hour_share = None
    if not cold_start:
        median = percentile(amounts, 50)
        p95 = percentile(amounts, config.amount_percentile)
        # Typical daily total: average total per day on which the user paid (IST days).
        active_days = {_ist(paid_at).date() for _, paid_at in context.approved_history}
        typical_daily = sum(amounts) / len(active_days)
        same_hour = sum(1 for _, paid_at in context.approved_history if _ist(paid_at).hour == int(hour))
        hour_share = same_hour / len(amounts)
        is_unusual_hour = hour_share < config.unusual_hour_share
    else:
        start, end = config.cold_start_unusual_hours
        is_unusual_hour = start <= hour < end

    sum_24h = context.approved_paise_in_daily_window + context.amount_paise
    return Features(
        amount_paise=context.amount_paise,
        hour_ist=hour,
        cold_start=cold_start,
        history_count=len(amounts),
        median_amount_paise=median,
        amount_p95_paise=p95,
        dormant_p90_paise=(
            context.lifetime_p90_paise
            if context.lifetime_approved_count >= config.cold_start_min_history
            else None
        ),
        lifetime_approved_count=context.lifetime_approved_count,
        typical_daily_total_paise=typical_daily,
        hour_share=hour_share,
        is_unusual_hour=is_unusual_hour,
        txn_count_10m=context.attempts_in_velocity_window,
        amount_sum_24h_paise=sum_24h,
        amount_sum_24h_ratio=(sum_24h / typical_daily) if typical_daily else None,
        repeat_same_payee_amount_5m=context.repeat_attempt_in_window,
        is_new_beneficiary=not context.beneficiary_has_approved_payment,
        beneficiary_age_hours=max(0.0, (context.at - context.beneficiary_created_at).total_seconds() / 3600),
        is_new_device=not context.device_seen_before,
        seconds_since_login=(
            max(0.0, (context.at - context.last_login_at).total_seconds()) if context.last_login_at else None
        ),
        days_since_last_txn=(
            max(0.0, (context.at - context.last_approved_at).total_seconds() / 86400)
            if context.last_approved_at
            else None
        ),
    )
