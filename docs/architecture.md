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

## P-3 implementation notes

- **System vs versioned routes.** `/`, `/health` (liveness) and `/health/ready` (readiness)
  are unversioned and live in `app/routes/system.py`. Every business router is added to
  `api_router` in `app/routes/__init__.py`, which is mounted once at `API_V1_PREFIX`.
  P-2 mounted the same health router at both `/health` and `/api/v1/health`; the duplicate
  was removed and the frontend now calls `/health` at the API origin.
- **Settings** (`app/core/config.py`): one class, profile chosen by `APP_ENV`; development
  defaults apply only to unset values; production rejects unsafe values at startup.
  `DATABASE_URL` and `JWT_SECRET_KEY` are `SecretStr`; logs use `database_url_masked`.
- **Database** (`app/database/session.py`): a `Database` object per app on
  `app.state.database`; lazy engine; `check_connection()` never raises; `DbSession`
  dependency rolls back on error and always closes. Missing configuration → 503
  `DATABASE_NOT_CONFIGURED`; connection failures and timeouts → 503 `DATABASE_UNAVAILABLE`.
- **Services commit explicitly**; the session dependency never auto-commits.

## P-4 implementation notes

Full schema: [`database-schema.md`](database-schema.md).

- Models in `app/models/` (one module per table, plus `enums.py` and `common.py`) on the
  shared `Base` from `app/database/base.py`.
- One risk assessment per transaction (unique `transaction_id`); assessments and audit logs
  are append-only in the ORM.
- `final_risk_score = round(0.6 × rule + 0.4 × ml)` is enforced by a CHECK constraint;
  rules-only rows have `final_risk_score = rule_score`. `compute_final_risk_score()` is the
  Python twin.
- Rule weights total 105 (open decision); `rule_score` is stored capped at 0–100.
- Beneficiary account references and UPI IDs are stored masked plus an HMAC fingerprint;
  the fingerprint key setting arrives with the beneficiary service.
- All foreign keys are `ON DELETE RESTRICT`; composite foreign keys enforce that payees,
  transactions and assessments linked together belong to the same user.
