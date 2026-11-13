"""Rule-based detection: P-1 rules R1-R6 as pure functions of the feature vector.

Each rule that fires yields one ``RuleHit`` with a plain-language label and detail
(shown to the user) and the observed values (stored in ``rule_details``, never
returned by the API). Wording follows P-1's copy rules: "unusual" or "higher
risk", never "fraud", and the user's own baseline next to the current value.
Details never state the trigger thresholds themselves.

Where P-1 defines no cold-start value (R3's daily-total clause) the baseline is
``None`` and the clause is not evaluated. R6's dormant clause uses the lifetime
90th percentile and is not evaluated below the minimum number of lifetime approved
payments (see ``features``).
"""

from dataclasses import dataclass, field
from typing import Any

from app.fraud_detection.config import RiskConfig
from app.fraud_detection.features import Features


@dataclass(frozen=True)
class RuleHit:
    rule: str
    code: str
    points: int
    label: str
    detail: str | None
    observed: dict[str, Any] = field(default_factory=dict)


def format_inr(paise: float) -> str:
    """Whole rupees with Indian digit grouping: 4800000 paise -> "₹48,000"."""
    rupees = str(int(round(paise / 100)))
    head, tail = rupees[:-3], rupees[-3:]
    groups = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return "₹" + ",".join([*groups, tail])


def format_time_ist(hour_ist: float) -> str:
    hour, minute = int(hour_ist), int(round((hour_ist % 1) * 60)) % 60
    return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _age(hours: float) -> str:
    if hours < 1:
        return "less than an hour ago"
    if hours < 48:
        return f"about {int(round(hours))} hour{'s' if round(hours) != 1 else ''} ago"
    return f"{int(hours // 24)} days ago"


def _r1(f: Features, c: RiskConfig) -> RuleHit | None:
    added_recently = f.beneficiary_age_hours < c.new_beneficiary_hours
    if not (f.is_new_beneficiary or added_recently):
        return None
    definition = c.rules["R1"]
    label = definition.label if f.is_new_beneficiary else "This beneficiary was added recently"
    return RuleHit(
        "R1", definition.code, definition.points, label, f"Added {_age(f.beneficiary_age_hours)}",
        {"is_new_beneficiary": f.is_new_beneficiary, "beneficiary_age_hours": round(f.beneficiary_age_hours, 2)},
    )


def _r2(f: Features, c: RiskConfig) -> RuleHit | None:
    definition = c.rules["R2"]
    if f.cold_start:
        if f.amount_paise <= c.cold_start_amount_paise:
            return None
        return RuleHit(
            "R2", definition.code, definition.points, "Large payment for an account with little history",
            f"{format_inr(f.amount_paise)} is large for an account that is still building a payment history",
            {"cold_start": True, "amount_paise": f.amount_paise},
        )
    if not (f.amount_paise > c.amount_median_multiple * f.median_amount_paise and f.amount_paise > f.amount_p95_paise):
        return None
    multiple = f.amount_paise / f.median_amount_paise
    return RuleHit(
        "R2", definition.code, definition.points, definition.label,
        f"{format_inr(f.amount_paise)} is about {multiple:.0f}× your typical payment of {format_inr(f.median_amount_paise)}",
        {"amount_paise": f.amount_paise, "median_amount_paise": f.median_amount_paise, "amount_p95_paise": f.amount_p95_paise},
    )


def _r3(f: Features, c: RiskConfig) -> RuleHit | None:
    attempt_number = f.txn_count_10m + 1  # this payment included
    burst = attempt_number >= c.velocity_min_payments
    # Not evaluated in cold start: P-1 defines no typical daily total there.
    daily = f.amount_sum_24h_ratio is not None and f.amount_sum_24h_ratio > c.daily_total_multiple
    repeat = f.repeat_same_payee_amount_5m
    if not (burst or daily or repeat):
        return None
    if burst:
        detail = f"{_ordinal(attempt_number)} payment attempt in {c.velocity_window_minutes} minutes"
    elif repeat:
        detail = "Same beneficiary and amount as a payment attempt a few minutes ago"
    else:
        detail = (
            f"Your payments in the last 24 hours ({format_inr(f.amount_sum_24h_paise)}) are about "
            f"{f.amount_sum_24h_ratio:.0f}× your usual daily total of {format_inr(f.typical_daily_total_paise)}"
        )
    definition = c.rules["R3"]
    return RuleHit(
        "R3", definition.code, definition.points, definition.label, detail,
        {"burst": burst, "daily_total": daily, "repeat": repeat, "txn_count_10m": f.txn_count_10m,
         "amount_sum_24h_ratio": None if f.amount_sum_24h_ratio is None else round(f.amount_sum_24h_ratio, 2)},
    )


def _r4(f: Features, c: RiskConfig) -> RuleHit | None:
    if not f.is_unusual_hour:
        return None
    definition = c.rules["R4"]
    label = "Payments at this time of night are less common" if f.cold_start else definition.label
    return RuleHit(
        "R4", definition.code, definition.points, label, f"Made at {format_time_ist(f.hour_ist)} IST",
        {"hour_ist": round(f.hour_ist, 2), "hour_share": f.hour_share, "cold_start": f.cold_start},
    )


def _r5(f: Features, c: RiskConfig) -> RuleHit | None:
    # A device is new unless the same user had an APPROVED payment from it in the last
    # 30 days (P-10 reading of P-1's "not seen"; unconfirmed attempts do not count).
    # P-1: "New device, or payment within 60s of login on a new device". The second
    # clause needs a new device too, so it never fires alone; it only adds detail.
    if not f.is_new_device:
        return None
    fresh_login = f.seconds_since_login is not None and f.seconds_since_login < c.fresh_login_seconds
    definition = c.rules["R5"]
    return RuleHit(
        "R5", definition.code, definition.points, definition.label,
        "Made within a minute of signing in" if fresh_login else None,
        {"is_new_device": True, "fresh_login": fresh_login},
    )


def _r6(f: Features, c: RiskConfig, fired: set[str]) -> RuleHit | None:
    definition = c.rules["R6"]
    # Clause 1: a new beneficiary (R1) combined with an unusual amount (R2).
    if {"R1", "R2"} <= fired:
        return RuleHit(
            "R6", definition.code, definition.points, definition.label,
            "A large first payment to a new payee is a common scam pattern", {"clause": "new_beneficiary_large_amount"},
        )
    # Clause 2: dormant account paying above its 90th percentile. The percentile is over
    # the user's lifetime approved payments, which must number at least the cold-start
    # minimum; there is no population fallback (P-1 defines none).
    dormant = f.days_since_last_txn is not None and f.days_since_last_txn >= c.dormant_days
    if dormant and f.dormant_p90_paise is not None and f.amount_paise > f.dormant_p90_paise:
        return RuleHit(
            "R6", definition.code, definition.points, "Large payment after a long gap",
            f"Your last approved payment was {int(f.days_since_last_txn)} days ago, and {format_inr(f.amount_paise)} "
            "is higher than almost all of your earlier payments",
            {"clause": "dormant_large_amount", "days_since_last_txn": round(f.days_since_last_txn, 1),
             "lifetime_approved_count": f.lifetime_approved_count},
        )
    return None


def evaluate(features: Features, config: RiskConfig) -> list[RuleHit]:
    """Run R1-R6 in order. R6 depends on whether R1 and R2 fired."""
    hits = [hit for hit in (_r1(features, config), _r2(features, config), _r3(features, config),
                            _r4(features, config), _r5(features, config)) if hit]
    r6 = _r6(features, config, {hit.rule for hit in hits})
    if r6:
        hits.append(r6)
    return hits
