"""Hybrid risk scoring, decision and explanation (P-1), as one pure function.

    features -> rules (R) -> ML scorer (M, optional) -> score S -> level -> decision

* R = min(100, sum of points of the rules that fired).
* S = 0.6 R + 0.4 M, or S = R when there is no ML score (the formula lives in
  ``app.models.compute_final_risk_score`` and is re-checked by the database).
* Level = the band S falls in. Without an ML score, LOW is raised to MEDIUM
  (P-1 fail-cautious). The score is never changed to match: a payment where no
  rule fired is stored as score 0, level MEDIUM, with a "limited assessment" factor.
* The decision (allowed actions, recommendation, deadline) follows from the level.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.fraud_detection.config import LIMITED_ASSESSMENT_CODE, LIMITED_ASSESSMENT_LABEL, RISK_CONFIG, RiskConfig
from app.fraud_detection.features import Features
from app.fraud_detection.ml import AnomalyScorer, MLResult, MLUnavailableError
from app.fraud_detection.rules import RuleHit, evaluate
from app.models import RiskLevel, compute_final_risk_score

logger = logging.getLogger("sakshampay.risk")

LIMITED_HISTORY_CODE = "LIMITED_HISTORY"
LIMITED_HISTORY_LABEL = "SakshamPay is still learning your payment patterns"


@dataclass(frozen=True)
class Decision:
    allowed_actions: list[str]
    recommended_action: str
    requires_confirmation: bool  # MEDIUM: Continue needs an explicit confirmation (P-1)
    expires_at: datetime


@dataclass(frozen=True)
class Assessment:
    rule_score: int
    raw_points_total: int
    ml_score: int | None
    final_score: int
    band_level: RiskLevel  # the band the score falls in
    risk_level: RiskLevel  # after the rules-only uplift, if any
    ml_unavailable_reason: str | None
    model_version: str | None
    ml_details: dict[str, Any] | None
    config_version: str
    rule_details: list[dict[str, Any]]
    factors: list[dict[str, Any]]  # user-facing, ordered
    features_snapshot: dict[str, Any]
    decision: Decision

    @property
    def ml_available(self) -> bool:
        return self.ml_score is not None

    @property
    def level_raised_from(self) -> RiskLevel | None:
        return self.band_level if self.band_level != self.risk_level else None


def decide(level: RiskLevel, config: RiskConfig, now: datetime) -> Decision:
    return Decision(
        allowed_actions=list(config.allowed_actions[level]),
        recommended_action=config.recommended_action[level],
        requires_confirmation=level == RiskLevel.MEDIUM,
        expires_at=now + config.decision_window,
    )


def _factor(code: str, source: str, label: str, detail: str | None = None, points: int | None = None) -> dict:
    return {"code": code, "source": source, "label": label, "detail": detail, "points": points}


def _score_ml(scorer: AnomalyScorer, features: Features) -> tuple[MLResult | None, str | None]:
    """ML failure never fails the assessment (P-1): any error means rules-only mode."""
    try:
        return scorer.score(features), None
    except MLUnavailableError as unavailable:
        return None, unavailable.reason
    except Exception as error:  # noqa: BLE001 - tolerate every scorer failure
        logger.exception("Anomaly scorer failed; continuing in rules-only mode")
        return None, f"SCORER_ERROR:{type(error).__name__}"


def assess(features: Features, *, scorer: AnomalyScorer, now: datetime, config: RiskConfig = RISK_CONFIG) -> Assessment:
    hits: list[RuleHit] = evaluate(features, config)
    raw_points = sum(hit.points for hit in hits)
    rule_score = min(config.rule_score_cap, raw_points)

    ml, ml_reason = _score_ml(scorer, features)
    ml_score = ml.score if ml else None
    final_score = compute_final_risk_score(rule_score, ml_score)

    band = config.band(final_score)
    level = RiskLevel.MEDIUM if ml is None and band == RiskLevel.LOW else band

    ranked = sorted(hits, key=lambda hit: (-hit.points, hit.rule))
    factors = [_factor(hit.code, "rule", hit.label, hit.detail, hit.points) for hit in ranked]
    if ml:
        factors.extend(ml.factors)
    if features.cold_start:
        factors.append(_factor(LIMITED_HISTORY_CODE, "system", LIMITED_HISTORY_LABEL))
    if ml is None:
        factors.append(_factor(LIMITED_ASSESSMENT_CODE, "system", LIMITED_ASSESSMENT_LABEL))

    decision = decide(level, config, now)
    rule_details: list[dict[str, Any]] = [
        {"rule": hit.rule, "code": hit.code, "points": hit.points, "observed": hit.observed} for hit in hits
    ]
    rule_details.append(
        {
            "summary": True,
            "raw_points_total": raw_points,
            "rule_score": rule_score,
            "band_level": band.value,
            "risk_level": level.value,
            "level_raised_from": band.value if band != level else None,
            "ml_unavailable_reason": ml_reason,
            "bands": {"low_max": config.low_max, "medium_max": config.medium_max},
            "recommended_action": decision.recommended_action,
            "requires_confirmation": decision.requires_confirmation,
        }
    )

    return Assessment(
        rule_score=rule_score,
        raw_points_total=raw_points,
        ml_score=ml_score,
        final_score=final_score,
        band_level=band,
        risk_level=level,
        ml_unavailable_reason=ml_reason,
        model_version=ml.model_version if ml else None,
        ml_details=ml.details if ml else None,
        config_version=config.version,
        rule_details=rule_details,
        factors=factors,
        features_snapshot=features.snapshot(),
        decision=decision,
    )
