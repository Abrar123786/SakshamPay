"""P-10a: the pure risk engine (config, features, rules R1-R6, scoring, decision).

No database. Every expected number comes from the P-1 architecture: points
20/25/20/10/15/15, cap 100, bands 0-30/31-65/66-100, 0.6/0.4 blend, rules-only
uplift, and the cold-start values for R2 and R4.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy
import pytest

from app.fraud_detection import engine, rules
from app.fraud_detection.config import IST, LIMITED_ASSESSMENT_CODE, RISK_CONFIG
from app.fraud_detection.engine import LIMITED_HISTORY_CODE, assess, decide
from app.fraud_detection.features import Features, PaymentContext, compute_features, percentile
from app.fraud_detection.ml import MLResult, UnavailableScorer
from app.models import RiskLevel, compute_final_risk_score

C = RISK_CONFIG
NOW = datetime(2026, 11, 10, 8, 30, tzinfo=UTC)  # 14:00 IST

# An established user making an ordinary payment: no rule fires.
ORDINARY = Features(
    amount_paise=500_00, hour_ist=14.0, cold_start=False, history_count=20,
    median_amount_paise=500_00, amount_p95_paise=2_000_00, dormant_p90_paise=1_500_00, lifetime_approved_count=20,
    typical_daily_total_paise=1_000_00, hour_share=0.2, is_unusual_hour=False,
    txn_count_10m=0, amount_sum_24h_paise=500_00, amount_sum_24h_ratio=0.5,
    repeat_same_payee_amount_5m=False, is_new_beneficiary=False, beneficiary_age_hours=500.0,
    is_new_device=False, seconds_since_login=600.0, days_since_last_txn=1.0,
)
COLD = replace(
    ORDINARY, cold_start=True, history_count=0, median_amount_paise=None, amount_p95_paise=None,
    dormant_p90_paise=None, lifetime_approved_count=0, typical_daily_total_paise=None, hour_share=None,
    amount_sum_24h_ratio=None, days_since_last_txn=None,
)


class FixedScorer:
    def __init__(self, score):
        self._score = score

    def score(self, features):
        return MLResult(score=self._score, model_version="test-model", details={"percentile": 0.9})


def fired(features):
    return [hit.rule for hit in rules.evaluate(features, C)]


def rules_only(features):
    return assess(features, scorer=UnavailableScorer(), now=NOW)


# ---- configuration -------------------------------------------------------------------------------

def test_rule_points_are_the_p1_values():
    assert {rule: definition.points for rule, definition in C.rules.items()} == {
        "R1": 20, "R2": 25, "R3": 20, "R4": 10, "R5": 15, "R6": 15,
    }
    assert sum(definition.points for definition in C.rules.values()) == 105  # capped at 100 by the engine
    assert (C.low_max, C.medium_max, C.rule_score_cap) == (30, 65, 100)
    assert (C.rule_weight, C.ml_weight) == (0.6, 0.4)
    assert C.decision_window == timedelta(minutes=10)
    assert C.cold_start_amount_paise == 25_000_00


def test_stored_formula_matches_the_configured_weights():
    for rule_score in range(0, 101, 5):
        for ml_score in range(0, 101, 5):
            exact = C.rule_weight * rule_score + C.ml_weight * ml_score
            assert abs(compute_final_risk_score(rule_score, ml_score) - exact) <= 0.5
        assert compute_final_risk_score(rule_score, None) == rule_score


def test_seed_sample_data_uses_the_same_constants():
    from seeds import dev_seed

    assert {rule: (points, code) for rule, (points, code, _label) in dev_seed.RULES.items()} == {
        rule: (definition.points, definition.code) for rule, definition in C.rules.items()
    }
    assert {level: tuple(actions) for level, actions in dev_seed.ALLOWED_ACTIONS.items()} == dict(C.allowed_actions)
    for score in range(101):
        for ml_available in (True, False):
            band = C.band(score)
            expected = RiskLevel.MEDIUM if not ml_available and band == RiskLevel.LOW else band
            assert dev_seed.risk_level_for(score, ml_available) == expected


@pytest.mark.parametrize(("score", "level"), [(0, "LOW"), (30, "LOW"), (31, "MEDIUM"), (65, "MEDIUM"), (66, "HIGH"), (100, "HIGH")])
def test_band_edges(score, level):
    assert C.band(score) == RiskLevel(level)


# ---- rules -----------------------------------------------------------------------------------------

def test_an_ordinary_payment_fires_nothing():
    assert fired(ORDINARY) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"is_new_beneficiary": True}, True),
        ({"beneficiary_age_hours": 23.99}, True),  # added under 24 hours ago, even if paid before
        ({"beneficiary_age_hours": 24.0}, False),
    ],
)
def test_r1_new_beneficiary(change, expected):
    assert ("R1" in fired(replace(ORDINARY, **change))) is expected


@pytest.mark.parametrize(
    ("amount", "median", "p95", "expected"),
    [
        (1_500_01, 500_00, 1_000_00, True),   # over 3x the median and above the 95th percentile
        (1_500_00, 500_00, 1_000_00, False),  # exactly 3x the median: not "over"
        (1_600_00, 500_00, 1_600_00, False),  # not above the 95th percentile
        (1_600_00, 600_00, 1_000_00, False),  # above p95 but not 3x the median
    ],
)
def test_r2_unusual_amount(amount, median, p95, expected):
    features = replace(ORDINARY, amount_paise=amount, median_amount_paise=median, amount_p95_paise=p95)
    assert ("R2" in fired(features)) is expected


@pytest.mark.parametrize(("amount", "expected"), [(25_000_00, False), (25_000_01, True)])
def test_r2_cold_start_uses_the_p1_amount(amount, expected):
    assert ("R2" in fired(replace(COLD, amount_paise=amount))) is expected


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"txn_count_10m": 1}, False),  # this is the 2nd attempt
        ({"txn_count_10m": 2}, True),   # this is the 3rd attempt in 10 minutes
        ({"amount_sum_24h_ratio": 3.0}, False),
        ({"amount_sum_24h_ratio": 3.01}, True),
        ({"repeat_same_payee_amount_5m": True}, True),
    ],
)
def test_r3_velocity(change, expected):
    assert ("R3" in fired(replace(ORDINARY, **change))) is expected


def test_r3_daily_total_clause_is_not_evaluated_in_cold_start():
    # P-1 defines no typical daily total for cold start, so there is no ratio to compare.
    assert COLD.amount_sum_24h_ratio is None
    assert "R3" not in fired(replace(COLD, amount_sum_24h_paise=90_000_00))


def test_r4_unusual_timing():
    assert "R4" in fired(replace(ORDINARY, is_unusual_hour=True))
    assert "R4" not in fired(ORDINARY)


def test_r5_new_device_and_the_redundant_fresh_login_clause():
    assert "R5" in fired(replace(ORDINARY, is_new_device=True))
    # "Within 60s of login on a new device" cannot fire without a new device.
    assert "R5" not in fired(replace(ORDINARY, is_new_device=False, seconds_since_login=5.0))
    hit = rules.evaluate(replace(ORDINARY, is_new_device=True, seconds_since_login=59.0), C)[0]
    assert (hit.points, hit.detail) == (15, "Made within a minute of signing in")
    assert rules.evaluate(replace(ORDINARY, is_new_device=True, seconds_since_login=60.0), C)[0].detail is None


def test_r6_needs_both_a_new_beneficiary_and_an_unusual_amount():
    large = {"amount_paise": 48_000_00, "median_amount_paise": 7_700_00, "amount_p95_paise": 20_000_00, "dormant_p90_paise": 60_000_00}
    assert fired(replace(ORDINARY, is_new_beneficiary=True, **large)) == ["R1", "R2", "R6"]
    assert "R6" not in fired(replace(ORDINARY, is_new_beneficiary=True))
    assert "R6" not in fired(replace(ORDINARY, **large))


@pytest.mark.parametrize(
    ("days", "amount", "expected"),
    [(30.0, 1_500_01, True), (29.9, 1_500_01, False), (30.0, 1_500_00, False)],
)
def test_r6_dormant_account_paying_above_its_90th_percentile(days, amount, expected):
    features = replace(ORDINARY, days_since_last_txn=days, amount_paise=amount, amount_p95_paise=50_000_00, median_amount_paise=1_000_00)
    assert ("R6" in fired(features)) is expected


def test_r6_dormant_clause_is_not_evaluated_without_history():
    assert "R6" not in fired(replace(COLD, days_since_last_txn=None, amount_paise=20_000_00))
    # History exists but fewer than five lifetime approved payments: no percentile.
    assert "R6" not in fired(replace(COLD, days_since_last_txn=200.0, amount_paise=20_000_00, lifetime_approved_count=4))


def test_r6_dormant_clause_fires_in_cold_start_from_the_lifetime_percentile():
    # A user back after 120 days: no 90-day history (cold start), 12 lifetime approved payments.
    returning = replace(COLD, days_since_last_txn=120.0, amount_paise=20_000_00, dormant_p90_paise=2_430_00,
                        lifetime_approved_count=12, history_count=0)
    (hit,) = [hit for hit in rules.evaluate(returning, C) if hit.rule == "R6"]
    assert hit.observed["clause"] == "dormant_large_amount" and hit.label == "Large payment after a long gap"
    assert "2,430" not in (hit.detail or "")  # the percentile itself is never shown


def test_explanations_never_say_fraud_and_never_show_thresholds():
    everything = replace(
        ORDINARY, amount_paise=48_000_00, median_amount_paise=7_700_00, amount_p95_paise=20_000_00,
        is_new_beneficiary=True, beneficiary_age_hours=2.0, is_unusual_hour=True, hour_ist=2.67,
        is_new_device=True, txn_count_10m=3, seconds_since_login=20.0,
    )
    hits = rules.evaluate(everything, C)
    assert [hit.rule for hit in hits] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    text = " ".join(f"{hit.label} {hit.detail or ''}" for hit in hits).lower()
    assert "fraud" not in text
    assert "25,000" not in text and "95" not in text and "3×" not in text
    by_rule = {hit.rule: hit.detail for hit in hits}
    assert by_rule["R1"] == "Added about 2 hours ago"
    assert by_rule["R2"] == "₹48,000 is about 6× your typical payment of ₹7,700"  # the P-1 example
    assert by_rule["R3"] == "4th payment attempt in 10 minutes"
    assert by_rule["R4"] == "Made at 2:40 AM IST"


@pytest.mark.parametrize(("paise", "text"), [(100, "₹1"), (99_999_00, "₹99,999"), (1_00_000_00, "₹1,00,000"), (12_34_56_789_00, "₹12,34,56,789")])
def test_indian_number_format(paise, text):
    assert rules.format_inr(paise) == text


# ---- scoring -----------------------------------------------------------------------------------------

def test_p1_worked_example():
    """P-1: a new beneficiary paying Rs 48,000 at 2:40 AM fires R1, R2, R4 and R6 for R = 70;
    with M = 82, S = round(42 + 32.8) = 75, which is HIGH."""
    features = replace(
        ORDINARY, amount_paise=48_000_00, median_amount_paise=7_700_00, amount_p95_paise=20_000_00,
        is_new_beneficiary=True, is_unusual_hour=True, hour_ist=2.67,
    )
    result = assess(features, scorer=FixedScorer(82), now=NOW)
    assert [d["rule"] for d in result.rule_details[:-1]] == ["R1", "R2", "R4", "R6"]
    assert (result.rule_score, result.ml_score, result.final_score, result.risk_level) == (70, 82, 75, RiskLevel.HIGH)
    assert result.decision.allowed_actions == ["VERIFY", "CANCEL"]
    assert result.model_version == "test-model" and result.ml_available


def test_rule_score_is_capped_at_100():
    everything = replace(
        ORDINARY, amount_paise=48_000_00, median_amount_paise=7_700_00, amount_p95_paise=20_000_00,
        is_new_beneficiary=True, is_unusual_hour=True, is_new_device=True, txn_count_10m=3,
    )
    result = rules_only(everything)
    assert (result.raw_points_total, result.rule_score, result.final_score) == (105, 100, 100)
    assert result.rule_details[-1]["raw_points_total"] == 105


def test_no_rule_fired_and_no_model_is_score_zero_level_medium():
    result = rules_only(ORDINARY)
    assert (result.rule_score, result.ml_score, result.final_score) == (0, None, 0)  # no points are invented
    assert (result.band_level, result.risk_level, result.level_raised_from) == (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.LOW)
    assert not result.ml_available and result.model_version is None and result.ml_details is None
    assert result.ml_unavailable_reason == "MODEL_NOT_IMPLEMENTED"
    assert [f["code"] for f in result.factors] == [LIMITED_ASSESSMENT_CODE]
    assert result.factors[0] == {
        "code": "LIMITED_ASSESSMENT", "source": "system", "points": None, "detail": None,
        "label": "Assessed with rules only; the behaviour model is not available",
    }
    assert result.decision.allowed_actions == ["CONTINUE", "VERIFY", "CANCEL"]
    assert result.rule_details[-1] == {
        "summary": True, "raw_points_total": 0, "rule_score": 0, "band_level": "LOW", "risk_level": "MEDIUM",
        "level_raised_from": "LOW", "ml_unavailable_reason": "MODEL_NOT_IMPLEMENTED",
        "bands": {"low_max": 30, "medium_max": 65}, "recommended_action": "VERIFY", "requires_confirmation": True,
    }


def test_rules_only_uplift_raises_low_only():
    medium = rules_only(replace(ORDINARY, is_new_beneficiary=True, is_new_device=True))  # 20 + 15
    assert (medium.final_score, medium.risk_level, medium.level_raised_from) == (35, RiskLevel.MEDIUM, None)
    high = rules_only(replace(ORDINARY, amount_paise=48_000_00, median_amount_paise=7_700_00, amount_p95_paise=20_000_00,
                              is_new_beneficiary=True, is_unusual_hour=True))  # 70
    assert (high.final_score, high.risk_level, high.level_raised_from) == (70, RiskLevel.HIGH, None)


def test_with_a_model_low_stays_low():
    result = assess(ORDINARY, scorer=FixedScorer(10), now=NOW)
    assert (result.final_score, result.risk_level, result.level_raised_from) == (4, RiskLevel.LOW, None)
    assert LIMITED_ASSESSMENT_CODE not in [f["code"] for f in result.factors]
    assert result.decision.allowed_actions == ["CONTINUE", "CANCEL"]


@pytest.mark.parametrize(("rule_points", "ml", "final", "level"), [(35, 23, 30, "LOW"), (35, 25, 31, "MEDIUM"), (70, 58, 65, "MEDIUM"), (70, 60, 66, "HIGH")])
def test_hybrid_score_band_edges(rule_points, ml, final, level):
    features = replace(ORDINARY, is_new_beneficiary=True, is_new_device=True)  # 35
    if rule_points == 70:
        features = replace(ORDINARY, amount_paise=48_000_00, median_amount_paise=7_700_00, amount_p95_paise=20_000_00,
                           is_new_beneficiary=True, is_unusual_hour=True)
    result = assess(features, scorer=FixedScorer(ml), now=NOW)
    assert (result.rule_score, result.final_score, result.risk_level) == (rule_points, final, RiskLevel(level))


def test_a_crashing_scorer_means_rules_only_not_failure():
    class Broken:
        def score(self, features):
            raise ZeroDivisionError("model blew up")

    result = assess(replace(ORDINARY, is_new_beneficiary=True), scorer=Broken(), now=NOW)
    assert (result.ml_score, result.final_score, result.risk_level) == (None, 20, RiskLevel.MEDIUM)
    assert result.ml_unavailable_reason == "SCORER_ERROR:ZeroDivisionError"


def test_factors_are_ranked_and_cold_start_is_explained():
    result = rules_only(replace(COLD, is_new_beneficiary=True, is_new_device=True, is_unusual_hour=True, hour_ist=2.0))
    assert [(f["code"], f["source"], f["points"]) for f in result.factors] == [
        ("NEW_BENEFICIARY", "rule", 20), ("NEW_DEVICE", "rule", 15), ("UNUSUAL_TIME", "rule", 10),
        (LIMITED_HISTORY_CODE, "system", None), (LIMITED_ASSESSMENT_CODE, "system", None),
    ]
    assert all(set(f) == {"code", "source", "label", "detail", "points"} for f in result.factors)


def test_assessment_carries_the_config_version_and_a_json_safe_snapshot():
    import json

    result = rules_only(ORDINARY)
    assert result.config_version == C.version == "risk-config-v1"
    json.dumps([result.rule_details, result.factors, result.features_snapshot])
    assert result.features_snapshot["amount_paise"] == 500_00


# ---- decision ------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("level", "allowed", "recommended", "confirm"),
    [
        ("LOW", ["CONTINUE", "CANCEL"], "CONTINUE", False),
        ("MEDIUM", ["CONTINUE", "VERIFY", "CANCEL"], "VERIFY", True),
        ("HIGH", ["VERIFY", "CANCEL"], "CANCEL", False),
    ],
)
def test_decision_table(level, allowed, recommended, confirm):
    decision = decide(RiskLevel(level), C, NOW)
    assert (decision.allowed_actions, decision.recommended_action, decision.requires_confirmation) == (allowed, recommended, confirm)
    assert decision.expires_at == NOW + timedelta(minutes=10)


def test_high_never_allows_continue():
    assert "CONTINUE" not in C.allowed_actions[RiskLevel.HIGH]


# ---- features --------------------------------------------------------------------------------------------

def context(**overrides):
    base = dict(
        amount_paise=500_00, at=NOW, beneficiary_created_at=NOW - timedelta(days=30),
        beneficiary_has_approved_payment=True, device_seen_before=True, last_login_at=NOW - timedelta(minutes=10),
        approved_history=[], last_approved_at=None, attempts_in_velocity_window=0,
        approved_paise_in_daily_window=0, repeat_attempt_in_window=False,
        lifetime_approved_count=0, lifetime_p90_paise=None,
    )
    return PaymentContext(**{**base, **overrides})


def history(amounts, *, hour_utc=8, days_ago_start=1):
    return [(amount, NOW.replace(hour=hour_utc) - timedelta(days=days_ago_start + i)) for i, amount in enumerate(amounts)]


@pytest.mark.parametrize("q", [0, 25, 50, 90, 95, 100])
def test_percentile_matches_numpy(q):
    values = [120_00, 50_00, 7_700_00, 300_00, 999_99, 48_000_00, 1_00, 2_500_00]
    assert percentile(values, q) == pytest.approx(float(numpy.percentile(values, q)))
    assert percentile([5], q) == 5


def test_cold_start_below_five_approved_payments():
    four = compute_features(context(approved_history=history([100_00] * 4)), C)
    assert four.cold_start and four.median_amount_paise is None and four.typical_daily_total_paise is None
    five = compute_features(context(approved_history=history([100_00, 200_00, 300_00, 400_00, 500_00])), C)
    assert not five.cold_start and five.history_count == 5
    assert (five.median_amount_paise, five.amount_p95_paise) == (300_00, 480_00)


@pytest.mark.parametrize(("count", "expected"), [(0, None), (4, None), (5, 2_430_00), (12, 2_430_00)])
def test_dormant_percentile_needs_five_lifetime_approved_payments(count, expected):
    # Independent of the 90-day history and of cold start.
    features = compute_features(context(lifetime_approved_count=count, lifetime_p90_paise=2_430_00 if count else None), C)
    assert features.cold_start and features.dormant_p90_paise == expected and features.lifetime_approved_count == count


def test_hour_is_taken_in_ist():
    features = compute_features(context(at=datetime(2026, 11, 9, 21, 10, tzinfo=UTC)), C)  # 02:40 IST next day
    assert features.hour_ist == pytest.approx(2 + 40 / 60)
    assert features.is_unusual_hour  # cold start: 00:00-05:00 IST
    assert not compute_features(context(at=datetime(2026, 11, 9, 23, 30, tzinfo=UTC)), C).is_unusual_hour  # 05:00 IST
    assert compute_features(context(at=datetime(2026, 11, 10, 2, 40, tzinfo=IST)), C).hour_ist == pytest.approx(2 + 40 / 60)


def test_unusual_hour_from_personal_history():
    past = history([100_00] * 20, hour_utc=8)  # all at 14:xx IST
    assert not compute_features(context(approved_history=past), C).is_unusual_hour  # also 14:00 IST
    evening = compute_features(context(approved_history=past, at=NOW.replace(hour=15)), C)  # 21:00 IST, 0% of history
    assert evening.is_unusual_hour and evening.hour_share == 0
    mixed = past[:19] + [(100_00, NOW.replace(hour=15) - timedelta(days=3))]  # exactly 5% at 21:xx IST
    assert not compute_features(context(approved_history=mixed, at=NOW.replace(hour=15)), C).is_unusual_hour


def test_typical_daily_total_is_the_average_per_active_day():
    past = [(300_00, NOW - timedelta(days=1)), (100_00, NOW - timedelta(days=1, minutes=5)),
            (200_00, NOW - timedelta(days=4)), (200_00, NOW - timedelta(days=9)), (200_00, NOW - timedelta(days=20))]
    features = compute_features(context(approved_history=past, approved_paise_in_daily_window=1_000_00, amount_paise=500_00), C)
    assert features.typical_daily_total_paise == 250_00  # Rs 1,000 over 4 active days
    assert features.amount_sum_24h_paise == 1_500_00  # approved in 24h plus this payment
    assert features.amount_sum_24h_ratio == 6.0


def test_beneficiary_device_login_and_gap_features():
    features = compute_features(
        context(beneficiary_created_at=NOW - timedelta(hours=2), beneficiary_has_approved_payment=False,
                device_seen_before=False, last_login_at=NOW - timedelta(seconds=45),
                last_approved_at=NOW - timedelta(days=40), attempts_in_velocity_window=2, repeat_attempt_in_window=True),
        C,
    )
    assert (features.is_new_beneficiary, features.beneficiary_age_hours, features.is_new_device) == (True, 2.0, True)
    assert (features.seconds_since_login, features.days_since_last_txn) == (45.0, 40.0)
    assert (features.txn_count_10m, features.repeat_same_payee_amount_5m) == (2, True)
    no_login = compute_features(context(last_login_at=None), C)
    assert no_login.seconds_since_login is None and no_login.days_since_last_txn is None


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_features(context(at=datetime(2026, 11, 10, 8, 30)), C)


def test_engine_module_has_no_database_access():
    import inspect

    for module in (engine, rules):
        source = inspect.getsource(module)
        assert "session" not in source.lower() and "sqlalchemy" not in source
