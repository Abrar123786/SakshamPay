# SakshamPay architecture (P-1 summary)

The full architecture document, with every diagram, is maintained here:
https://claude.ai/artifact/FyUo3DKWQ8jADLsmkNpsEP

This file records the decisions that implementation must follow.

## Shape

- Modular monolith: React + Vite + Tailwind (Vercel) → FastAPI + SQLAlchemy (Render) → PostgreSQL.
- Routers validate and delegate; services hold logic; repositories own queries; the fraud
  engine after feature extraction is pure functions.

## Transaction lifecycle

States: `INITIATED`, `ANALYSED`, `AWAITING_USER_ACTION`, `APPROVED`, `CANCELLED`,
`EXPIRED`, `FAILED`.

- Assessment runs synchronously inside `POST /api/v1/transactions`.
- The user acts through one endpoint, `POST /api/v1/transactions/{id}/actions`
  (`CANCEL` | `CONTINUE` | `VERIFY`).
- Only the Transaction service changes status. Nothing reaches `APPROVED` without a stored
  assessment and an explicit user action. HIGH risk requires `VERIFY` (step-up re-auth).

## Risk scoring (initial, configurable values)

- Rules R1–R6: new beneficiary 20, unusual amount 25, velocity 20, timing 10,
  device/session 15, behavioural deviation 15; rule score capped at 100.
- Isolation Forest anomaly `a = -score_samples(x)`, ranked against held-out normal data and
  mapped piecewise to 0–100. It is a rank of unusualness, not a fraud probability.
- Combined `S = round(0.6 × R + 0.4 × M)`; LOW 0–30, MEDIUM 31–65, HIGH 66–100.
- ML unavailable → rules only, LOW raised to MEDIUM.

## Data

Six tables: `users`, `beneficiaries`, `transactions`, `risk_assessments`, `alerts`,
`audit_logs`. Amounts in integer paise. `(user_id, idempotency_key)` is unique.

## Security

Argon2id password hashing; JWT HS256, 30-minute access token kept in `sessionStorage`
(no refresh token in v1); CORS allowlist; one error shape
`{"error": {"code", "message", "request_id"}}`; API docs disabled in production.

## P-2 implementation notes

| P-1 name | P-2 directory |
| --- | --- |
| `app/api/` | `app/routes/` |
| `app/db/` | `app/database/` (engine, session, base) + `app/models/` + `app/repositories/` |
| `app/fraud/` | `app/fraud_detection/` |
