"""Fraud detection engine (P-1): feature vector, rule-based detection (R1-R6), hybrid
risk scoring, decision and explanations, driven by the versioned ``config.RISK_CONFIG``.

Everything in this package is pure (no database access). The Isolation Forest
anomaly model is not built yet: ``ml.UnavailableScorer`` puts every assessment in
P-1's rules-only mode until a later phase ships a trained model.
"""
