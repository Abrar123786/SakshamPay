"""P-10b: feature extraction against PostgreSQL (history windows, statuses, ownership)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.fraud_detection.config import RISK_CONFIG
from app.models import TransactionStatus
from app.services.feature_extraction import FeatureExtractor
from tests.payments_support import DEVICE, add_payment, make_beneficiary, make_user
from tests.pg import require_postgres_url, rollback_session, throwaway_schema

PG_URL = require_postgres_url()
S = TransactionStatus
NOW = datetime(2026, 11, 10, 8, 30, tzinfo=UTC)  # 14:00 IST


@pytest.fixture(scope="module")
def engine():
    with throwaway_schema(PG_URL) as engine:
        yield engine


@pytest.fixture
def session(engine):
    with rollback_session(engine) as session:
        yield session


def ago(**delta):
    return NOW - timedelta(**delta)


def features_for(session, user, beneficiary, amount=500_00, *, device=DEVICE):
    current = add_payment(session, user, beneficiary, amount, at=NOW, status=S.INITIATED, device_id=device)
    features = FeatureExtractor(session).build(current, beneficiary=beneficiary, user=user)
    assert not session.new and not session.dirty  # extraction only reads
    return features


def test_a_new_users_first_payment(session):
    user = make_user(session, last_login_at=ago(seconds=30))
    beneficiary = make_beneficiary(session, user, created_at=ago(hours=3))
    features = features_for(session, user, beneficiary)
    assert features.cold_start and features.history_count == 0
    assert features.is_new_beneficiary and features.is_new_device
    assert features.beneficiary_age_hours == 3.0
    assert features.seconds_since_login == 30.0
    assert features.days_since_last_txn is None and features.amount_sum_24h_ratio is None
    assert (features.txn_count_10m, features.amount_sum_24h_paise, features.repeat_same_payee_amount_5m) == (0, 500_00, False)
    assert features.hour_ist == 14.0


def test_baselines_use_only_this_users_approved_payments_in_90_days(session):
    user, other = make_user(session), make_user(session)
    beneficiary, theirs = make_beneficiary(session, user), make_beneficiary(session, other)
    for days, amount in enumerate([100_00, 200_00, 300_00, 400_00, 500_00], start=2):
        add_payment(session, user, beneficiary, amount, at=ago(days=days))
    add_payment(session, user, beneficiary, 9_000_00, at=ago(days=91))  # too old
    add_payment(session, user, beneficiary, 9_000_00, at=ago(days=3), status=S.CANCELLED)
    add_payment(session, user, beneficiary, 9_000_00, at=ago(days=3), status=S.EXPIRED)
    add_payment(session, user, beneficiary, 9_000_00, at=ago(days=3), status=S.FAILED)
    add_payment(session, user, beneficiary, 9_000_00, at=ago(days=3), status=S.AWAITING_USER_ACTION)
    add_payment(session, other, theirs, 9_000_00, at=ago(days=3))  # someone else's
    add_payment(session, user, beneficiary, 9_000_00, at=NOW + timedelta(minutes=1))  # later than this payment

    features = features_for(session, user, beneficiary)
    assert not features.cold_start and features.history_count == 5
    assert (features.median_amount_paise, features.amount_p95_paise) == (300_00, 480_00)
    assert features.typical_daily_total_paise == 300_00  # Rs 1,500 over 5 active days
    assert not features.is_new_beneficiary
    assert features.days_since_last_txn == pytest.approx(2.0)


def test_cold_start_boundary_is_five_approved_payments(session):
    user = make_user(session)
    beneficiary = make_beneficiary(session, user)
    for days in range(1, 5):
        add_payment(session, user, beneficiary, 100_00, at=ago(days=days))
    assert features_for(session, user, beneficiary).cold_start
    add_payment(session, user, beneficiary, 100_00, at=ago(days=6))
    current = add_payment(session, user, beneficiary, 100_00, at=NOW, status=S.INITIATED)
    assert not FeatureExtractor(session).build(current, beneficiary=beneficiary, user=user).cold_start


def test_velocity_counts_every_attempt_in_ten_minutes(session):
    user = make_user(session)
    beneficiary = make_beneficiary(session, user)
    add_payment(session, user, beneficiary, 100_00, at=ago(minutes=2), status=S.CANCELLED)
    add_payment(session, user, beneficiary, 200_00, at=ago(minutes=9), status=S.FAILED)
    add_payment(session, user, beneficiary, 300_00, at=ago(minutes=9, seconds=59), status=S.AWAITING_USER_ACTION)
    add_payment(session, user, beneficiary, 400_00, at=ago(minutes=10, seconds=1))  # outside the window
    assert features_for(session, user, beneficiary).txn_count_10m == 3


def test_daily_total_uses_approved_payments_in_24_hours_plus_this_one(session):
    user = make_user(session)
    beneficiary = make_beneficiary(session, user)
    add_payment(session, user, beneficiary, 1_000_00, at=ago(hours=23))
    add_payment(session, user, beneficiary, 2_000_00, at=ago(hours=5))
    add_payment(session, user, beneficiary, 9_000_00, at=ago(hours=5), status=S.CANCELLED)
    add_payment(session, user, beneficiary, 9_000_00, at=ago(hours=25))
    assert features_for(session, user, beneficiary, 500_00).amount_sum_24h_paise == 3_500_00


def test_repeat_is_same_beneficiary_and_amount_within_five_minutes(session):
    user = make_user(session)
    beneficiary, another = make_beneficiary(session, user), make_beneficiary(session, user, name="Meera")
    add_payment(session, user, another, 500_00, at=ago(minutes=1))            # different beneficiary
    add_payment(session, user, beneficiary, 500_01, at=ago(minutes=1))        # different amount
    add_payment(session, user, beneficiary, 500_00, at=ago(minutes=5, seconds=1))  # too long ago
    assert not features_for(session, user, beneficiary, 500_00).repeat_same_payee_amount_5m
    add_payment(session, user, beneficiary, 500_00, at=ago(minutes=4), status=S.CANCELLED)  # any status counts
    current = add_payment(session, user, beneficiary, 500_00, at=NOW, status=S.INITIATED)
    assert FeatureExtractor(session).build(current, beneficiary=beneficiary, user=user).repeat_same_payee_amount_5m


def is_new_device(session, user, beneficiary):
    current = add_payment(session, user, beneficiary, 100_00, at=NOW, status=S.INITIATED, device_id=DEVICE)
    return FeatureExtractor(session).build(current, beneficiary=beneficiary, user=user).is_new_device


def test_device_history_is_per_user_and_approved_only(session):
    user, other = make_user(session), make_user(session)
    beneficiary, theirs = make_beneficiary(session, user), make_beneficiary(session, other)
    add_payment(session, other, theirs, 100_00, at=ago(days=1), device_id=DEVICE)  # same device, another user
    add_payment(session, user, beneficiary, 100_00, at=ago(days=1), device_id="another-device-9999")  # another device
    assert is_new_device(session, user, beneficiary)
    add_payment(session, user, beneficiary, 100_00, at=ago(days=29), device_id=DEVICE)  # approved, in the window
    assert not is_new_device(session, user, beneficiary)


@pytest.mark.parametrize("status", [S.INITIATED, S.FAILED, S.ANALYSED, S.AWAITING_USER_ACTION, S.EXPIRED, S.CANCELLED])
def test_unapproved_attempts_never_make_a_device_known(session, status):
    user = make_user(session)
    beneficiary = make_beneficiary(session, user)
    add_payment(session, user, beneficiary, 100_00, at=ago(minutes=30), device_id=DEVICE, status=status)
    assert is_new_device(session, user, beneficiary)


@pytest.mark.parametrize(("age", "known"), [(timedelta(days=29, hours=23), True), (timedelta(days=30), True), (timedelta(days=30, seconds=1), False)])
def test_device_window_is_30_days_and_includes_its_start(session, age, known):
    user = make_user(session)
    beneficiary = make_beneficiary(session, user)
    add_payment(session, user, beneficiary, 100_00, at=NOW - age, device_id=DEVICE)
    assert is_new_device(session, user, beneficiary) is not known


def test_new_beneficiary_means_no_approved_payment_to_them_yet(session):
    user = make_user(session)
    old, new = make_beneficiary(session, user, created_at=ago(days=60)), make_beneficiary(session, user, name="New", created_at=ago(days=60))
    add_payment(session, user, old, 100_00, at=ago(days=10))
    add_payment(session, user, new, 100_00, at=ago(days=10), status=S.CANCELLED)  # never approved
    assert features_for(session, user, new).is_new_beneficiary
    current = add_payment(session, user, old, 100_00, at=NOW, status=S.INITIATED)
    assert not FeatureExtractor(session).build(current, beneficiary=old, user=user).is_new_beneficiary


def test_dormancy_looks_beyond_the_90_day_window(session):
    user = make_user(session)
    beneficiary = make_beneficiary(session, user)
    add_payment(session, user, beneficiary, 100_00, at=ago(days=200))
    features = features_for(session, user, beneficiary)
    assert features.days_since_last_txn == pytest.approx(200.0)
    assert features.cold_start and features.lifetime_approved_count == 1
    assert features.dormant_p90_paise is None  # fewer than five lifetime approved payments


RETURNING_AMOUNTS = [1_200_00] * 6 + [1_800_00] * 4 + [2_500_00, 3_000_00]  # lifetime p90 = Rs 2,430


def returning_user(session, *, amounts=RETURNING_AMOUNTS, last_days_ago=121):
    """Approved payments between 300 and ``last_days_ago`` days ago, then nothing."""
    user = make_user(session)
    beneficiary = make_beneficiary(session, user, created_at=ago(days=400))
    for i, amount in enumerate(amounts):
        add_payment(session, user, beneficiary, amount, at=ago(days=last_days_ago + i * 10), device_id=DEVICE)
    return user, beneficiary


def test_lifetime_dormant_baseline_for_a_user_back_after_120_days(session):
    user, beneficiary = returning_user(session, last_days_ago=120)
    features = features_for(session, user, beneficiary, 20_000_00)
    assert features.cold_start and features.history_count == 0  # 90-day baselines unchanged
    assert features.median_amount_paise is None and features.amount_p95_paise is None
    assert features.lifetime_approved_count == 12 and features.dormant_p90_paise == pytest.approx(2_430_00)
    assert features.days_since_last_txn == pytest.approx(120.0)
    assert features.is_new_device  # the device's last approved payment was 120 days ago


def test_lifetime_percentile_matches_the_engine_percentile(session):
    import random

    from app.fraud_detection.features import percentile

    amounts = [random.Random(7).randint(100, 5_000_000) for _ in range(37)]
    user, beneficiary = returning_user(session, amounts=amounts)
    features = features_for(session, user, beneficiary)
    assert features.dormant_p90_paise == pytest.approx(percentile(amounts, 90), abs=1)


def test_lifetime_baseline_counts_only_this_users_earlier_approved_payments(session):
    user, beneficiary = returning_user(session, amounts=[1_000_00] * 5)
    other = make_user(session)
    theirs = make_beneficiary(session, other)
    for status in (S.CANCELLED, S.EXPIRED, S.FAILED, S.INITIATED, S.AWAITING_USER_ACTION):
        add_payment(session, user, beneficiary, 90_000_00, at=ago(days=200), status=status)
    add_payment(session, other, theirs, 90_000_00, at=ago(days=200))  # another user's approved payment
    add_payment(session, user, beneficiary, 90_000_00, at=NOW + timedelta(minutes=1))  # later than this payment
    features = features_for(session, user, beneficiary)
    assert (features.lifetime_approved_count, features.dormant_p90_paise) == (5, 1_000_00)


@pytest.mark.parametrize(("payments", "fires"), [(4, False), (5, True)])
def test_dormant_clause_needs_five_lifetime_approved_payments(session, payments, fires):
    from app.fraud_detection.rules import evaluate

    user, beneficiary = returning_user(session, amounts=[1_000_00] * payments)
    hits = evaluate(features_for(session, user, beneficiary, 20_000_00), RISK_CONFIG)
    assert ("R6" in [hit.rule for hit in hits]) is fires


@pytest.mark.parametrize(("idle", "fires"), [(timedelta(days=29, hours=23), False), (timedelta(days=30), True)])
def test_dormancy_boundary_is_30_days(session, idle, fires):
    from app.fraud_detection.rules import evaluate

    user = make_user(session)
    beneficiary = make_beneficiary(session, user, created_at=ago(days=400))
    add_payment(session, user, beneficiary, 1_000_00, at=NOW - idle)
    for days in range(60, 100, 10):
        add_payment(session, user, beneficiary, 1_000_00, at=ago(days=days))
    hits = evaluate(features_for(session, user, beneficiary, 5_000_00), RISK_CONFIG)
    assert ("R6" in [hit.rule for hit in hits]) is fires


def test_rules_fire_from_extracted_features(session):
    from app.fraud_detection.rules import evaluate

    user = make_user(session, last_login_at=ago(minutes=30))
    beneficiary, new = make_beneficiary(session, user, created_at=ago(days=80)), make_beneficiary(session, user, name="New", created_at=ago(hours=2))
    for days in range(1, 21):
        add_payment(session, user, beneficiary, 7_700_00, at=ago(days=days), device_id=DEVICE)
    features = features_for(session, user, new, 48_000_00)
    assert [hit.rule for hit in evaluate(features, RISK_CONFIG)] == ["R1", "R2", "R3", "R6"]  # R3: 24h total far above typical
