"""ML anomaly scoring: the interface only.

No model exists yet. The Isolation Forest, its training data and its calibration
are built in later phases (P-1 "ML anomaly detection"). Until then the engine uses
``UnavailableScorer``, which always reports that no ML score is available, and the
assessment runs in P-1's rules-only mode. Nothing here produces or imitates an ML
score.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.fraud_detection.features import Features


class MLUnavailableError(Exception):
    """The anomaly model cannot score this payment; ``reason`` is recorded in the audit log."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class MLResult:
    score: int  # calibrated 0-100 rank of unusualness (P-1), never a fraud probability
    model_version: str
    details: dict[str, Any] = field(default_factory=dict)
    factors: tuple[dict[str, Any], ...] = ()  # "most unusual attributes" for the explanation


class AnomalyScorer(Protocol):
    def score(self, features: Features) -> MLResult:
        """Return a calibrated score, or raise MLUnavailableError."""


class UnavailableScorer:
    """Used until a trained model is shipped: every call reports "no model"."""

    reason = "MODEL_NOT_IMPLEMENTED"

    def score(self, features: Features) -> MLResult:
        raise MLUnavailableError(self.reason)
