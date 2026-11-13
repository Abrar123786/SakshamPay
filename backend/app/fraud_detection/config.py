"""The versioned risk configuration (P-1 "Configuration and versioning").

Every tunable number of the risk engine lives here, and every stored assessment
records ``version``. Change a value -> change ``version``.

Source of each value:
  * "P-1": stated in the approved P-1 architecture; do not change silently.
  * "P-10": P-1 leaves it open; the reading approved for P-10 is noted beside it.

The hybrid formula itself (final = 0.6 x rules + 0.4 x ML, or the rule score alone
when there is no ML score) is not configurable here: it is fixed by
``app.models.compute_final_risk_score`` and a database CHECK constraint.
"""

from dataclasses import dataclass, field
from datetime import timedelta, timezone
from types import MappingProxyType
from typing import Mapping

from app.models import RiskLevel

IST = timezone(timedelta(hours=5, minutes=30), "IST")


@dataclass(frozen=True)
class RuleDefinition:
    rule: str  # "R1".."R6"
    code: str
    points: int
    label: str  # plain-language factor shown to the user


@dataclass(frozen=True)
class RiskConfig:
    version: str = "risk-config-v1"

    # ---- hybrid score (P-1 D6), for documentation and tests; enforced elsewhere ----
    rule_weight: float = 0.6
    ml_weight: float = 0.4
    rule_score_cap: int = 100

    # ---- bands (P-1): LOW 0-30, MEDIUM 31-65, HIGH 66-100 ----
    low_max: int = 30
    medium_max: int = 65

    # ---- history (P-1) ----
    history_days: int = 90
    cold_start_min_history: int = 5  # fewer approved payments in the window -> cold start (P-10 reading)

    # ---- R1 new beneficiary (P-1) ----
    new_beneficiary_hours: int = 24

    # ---- R2 unusual amount (P-1) ----
    amount_median_multiple: int = 3
    amount_percentile: int = 95
    cold_start_amount_paise: int = 25_000 * 100

    # ---- R3 velocity (P-1) ----
    velocity_window_minutes: int = 10
    velocity_min_payments: int = 3  # this payment is at least the 3rd attempt (P-10 reading)
    daily_total_multiple: int = 3
    daily_total_window_hours: int = 24
    repeat_window_minutes: int = 5

    # ---- R4 unusual timing (P-1) ----
    unusual_hour_share: float = 0.05
    cold_start_unusual_hours: tuple[int, int] = (0, 5)  # 00:00 <= IST time < 05:00

    # ---- R5 device or session (P-1) ----
    device_history_days: int = 30  # "seen" = on an APPROVED payment in this window (P-10 reading)
    fresh_login_seconds: int = 60

    # ---- R6 behavioural deviation (P-1) ----
    dormant_days: int = 30
    dormant_percentile: int = 90  # over lifetime approved payments, at least cold_start_min_history (P-10 reading)

    # ---- decision engine (P-1) ----
    decision_window: timedelta = timedelta(minutes=10)
    stale_initiated_after: timedelta = timedelta(minutes=2)

    # ---- step-up verification: P-1 says "rate-limited" without numbers (P-10 reading:
    #      the same numbers as the login lockout) ----
    verify_failure_limit: int = 5
    verify_failure_window: timedelta = timedelta(minutes=15)

    rules: Mapping[str, RuleDefinition] = field(
        default_factory=lambda: MappingProxyType(
            {
                "R1": RuleDefinition("R1", "NEW_BENEFICIARY", 20, "First payment to this beneficiary"),
                "R2": RuleDefinition("R2", "UNUSUAL_AMOUNT", 25, "Amount is far above your usual payments"),
                "R3": RuleDefinition("R3", "HIGH_VELOCITY", 20, "Several payments in a short time"),
                "R4": RuleDefinition("R4", "UNUSUAL_TIME", 10, "You rarely pay at this time of day"),
                "R5": RuleDefinition("R5", "NEW_DEVICE", 15, "First payment from this device"),
                "R6": RuleDefinition("R6", "BEHAVIOUR_DEVIATION", 15, "Large first payment to a new payee"),
            }
        )
    )

    # Allowed actions per level (P-1 decision engine), in display order.
    allowed_actions: Mapping[RiskLevel, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType(
            {
                RiskLevel.LOW: ("CONTINUE", "CANCEL"),
                RiskLevel.MEDIUM: ("CONTINUE", "VERIFY", "CANCEL"),
                RiskLevel.HIGH: ("VERIFY", "CANCEL"),
            }
        )
    )
    # P-1: MEDIUM "Verify recommended"; HIGH "Cancel is the default". P-1 names no
    # recommendation for LOW (P-10 reading: Continue, as LOW has no warning).
    recommended_action: Mapping[RiskLevel, str] = field(
        default_factory=lambda: MappingProxyType(
            {RiskLevel.LOW: "CONTINUE", RiskLevel.MEDIUM: "VERIFY", RiskLevel.HIGH: "CANCEL"}
        )
    )

    def band(self, score: int) -> RiskLevel:
        """The band a 0-100 score falls in (before any rules-only uplift)."""
        if score <= self.low_max:
            return RiskLevel.LOW
        if score <= self.medium_max:
            return RiskLevel.MEDIUM
        return RiskLevel.HIGH


RISK_CONFIG = RiskConfig()

# Factor shown when the assessment ran without the anomaly model (P-1 rules-only mode).
LIMITED_ASSESSMENT_CODE = "LIMITED_ASSESSMENT"
LIMITED_ASSESSMENT_LABEL = "Assessed with rules only; the behaviour model is not available"
