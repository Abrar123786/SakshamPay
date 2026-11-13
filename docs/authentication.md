# SakshamPay authentication (P-6)

Email-and-password sign-in issuing short-lived JWT access tokens. This guide covers the
backend; the sign-in screens (P-8) are described in
[`frontend-authentication.md`](frontend-authentication.md). All commands are PowerShell,
run from `backend` with the virtual environment active.

## Architecture

```text
POST /api/v1/auth/register ─┐
POST /api/v1/auth/login ────┼─> routes/auth.py ─> services/auth.py ─> repositories (users, audit_logs, alerts)
GET  /api/v1/auth/me ───────┘          │                 │
                                       │                 └─ core/security.py: Argon2id hashing, JWT create/verify
                                       └─ routes/dependencies.py: CurrentUser (bearer token -> active User)
```

| Piece | Responsibility |
| --- | --- |
| `app/core/security.py` | Argon2id password hashing and verification; JWT creation and validation; auth error types |
| `app/services/auth.py` | Registration and login rules, lockout, audit events; commits each operation |
| `app/routes/dependencies.py` | `CurrentUser`: protects any endpoint (`def handler(user: CurrentUser): ...`) |
| `app/routes/auth.py` | The three endpoints |
| `app/schemas/auth.py` | Request validation and the safe `UserProfile` response |

No database change was needed: the P-4 `users` table already has `password_hash`
(Argon2id-only by CHECK constraint), `is_active` and the lockout fields
`failed_login_count`, `locked_until` and `last_login_at`.

### Passwords

- Hashed with Argon2id (`argon2-cffi`, RFC 9106 defaults: 64 MiB memory, 3 iterations,
  4 lanes, random 16-byte salt). The database rejects anything that is not an Argon2id hash.
- Rules: 10–128 characters, not only spaces, not equal to the email address.
- If the hashing parameters are strengthened later, a user's hash is upgraded at their next
  successful login.

### Access tokens

- HS256, signed with `JWT_SECRET_KEY`; lifetime `ACCESS_TOKEN_EXPIRE_MINUTES` (30).
- Claims: exactly `sub` (user UUID), `iat`, `exp`. No refresh tokens (v1 design).
- Rejected: expired, wrong signature, malformed, other algorithms (including `alg: none`),
  missing or non-UUID `sub`, issued in the future, and tokens for users that do not exist or
  are deactivated.
- The user is identified only from the token. Request bodies, query strings and paths are
  never used to decide who is signed in.

### Login and lockout

- Every failure returns the same `401 INVALID_CREDENTIALS` with the message "Invalid email
  or password.": unknown email, wrong password, locked account and deactivated account
  alike. Each path runs one full Argon2id check, so timing does not reveal which happened.
- `LOGIN_MAX_FAILED_ATTEMPTS` (5) consecutive wrong passwords lock sign-in for
  `LOGIN_LOCKOUT_MINUTES` (15). While locked, passwords are not checked at all. The lock
  creates an `ACCOUNT_LOCKED` alert for the user. A successful login resets the counter.
- Audit log events: `USER_REGISTERED`, `LOGIN_SUCCEEDED`, `LOGIN_FAILED` (with the real
  reason, visible only in the audit table) and `ACCOUNT_LOCKED`. Passwords, hashes and
  tokens are never logged or audited.

### Login limit per network (P-1: "per account and IP prefix")

The lockout above is the per-account limit. The per-network limit is implemented but
**off by default** (`LOGIN_PREFIX_LIMIT_ENABLED=false`):

- With it on, `LOGIN_PREFIX_FAILURE_LIMIT` (20) failed logins from one network (IPv4 /24,
  IPv6 /48; IPv4-mapped IPv6 as its IPv4 /24) in 15 minutes return
  `429 TOO_MANY_LOGIN_ATTEMPTS` ("Too many unsuccessful sign-in attempts. Please wait a few
  minutes and try again."). Every `LOGIN_FAILED` counts: wrong passwords, unknown emails,
  locked and deactivated accounts, from any account.
- The answer does not depend on the email, so it reveals nothing about which accounts
  exist.
- Counted from `LOGIN_FAILED` audit rows, which already hold the truncated network: no new
  data is stored and no migration was needed.
- Order of work: an unlocked early check; then the account lookup and one Argon2id check,
  with no network lock held; then `pg_advisory_xact_lock(51003, hashtext(network))`, a
  recount, and refusal at the limit **whatever the password was** (otherwise the limit
  would confirm a right guess). Only after that is anything written. A refused attempt
  records nothing: no audit row and no change to the account's failure counter, so a
  blocked attacker cannot also lock the account.
- Concurrent failures from one network are counted exactly; the limit is never exceeded.
  Lock order: network lock, then the user row. Verify holds a user row but never waits for
  this lock, so the two cannot deadlock.
- A lock wait over 2 seconds returns `503 SERVICE_BUSY` with nothing written.
- Requests whose address is unknown or invalid are never pooled together.

**Before turning it on in production** the app must see real client addresses. Behind
Render's proxy that means `FORWARDED_ALLOW_IPS` (see the last item under Known
limitations). Otherwise every client shares the proxy's network and one attacker could
block sign-in for everyone. Check it the same way as for Verify
([`payments.md`](payments.md#verification-step-up)): two failed logins from two different
networks must give two `LOGIN_FAILED` rows with different `ip_address` values.

## Endpoints

All errors use the standard format `{"error": {"code", "message", "request_id"}}`.

### POST /api/v1/auth/register

```json
{ "full_name": "Asha Rao", "email": "asha.rao@example.com", "phone_number": "+919876543210", "password": "a-long-passphrase" }
```

`phone_number` is optional (international format; spaces and dashes are removed). The email
is stored lower-case. Unknown fields are refused.

| Status | Meaning |
| --- | --- |
| 201 | Created; body is the user profile (below). It does not sign the user in. |
| 409 | `EMAIL_ALREADY_REGISTERED` or `PHONE_ALREADY_REGISTERED` |
| 422 | `VALIDATION_ERROR` with `details` (field location, message, type; never the value) |

### POST /api/v1/auth/login

```json
{ "email": "asha.rao@example.com", "password": "a-long-passphrase" }
```

| Status | Meaning |
| --- | --- |
| 200 | `{"access_token": "...", "token_type": "bearer", "expires_in": 1800, "expires_at": "2026-11-09T10:30:00Z"}` |
| 401 | `INVALID_CREDENTIALS` (all failure reasons) |
| 422 | `VALIDATION_ERROR` |
| 429 | `TOO_MANY_LOGIN_ATTEMPTS` (only with the per-network limit on) |
| 503 | `AUTH_NOT_CONFIGURED` (no usable `JWT_SECRET_KEY`), a database error, or `SERVICE_BUSY` |

### GET /api/v1/auth/me

Header `Authorization: Bearer <access_token>`.

| Status | Meaning |
| --- | --- |
| 200 | `{"id", "full_name", "email", "phone_number", "is_active", "created_at"}` |
| 401 | `NOT_AUTHENTICATED` (no bearer token), `INVALID_TOKEN` or `TOKEN_EXPIRED`; includes `WWW-Authenticate: Bearer` |
| 503 | `AUTH_NOT_CONFIGURED` |

The profile never contains the password hash or the lockout fields.

## Environment variables

In `backend\.env` (edit with `notepad .env`; never commit it):

| Variable | Default | Notes |
| --- | --- | --- |
| `JWT_SECRET_KEY` | none | **Required for sign-in in every environment**, 32+ characters. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Changing it signs everyone out. |
| `JWT_ALGORITHM` | `HS256` | Only HS256 is accepted |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | 1–1440 |
| `LOGIN_MAX_FAILED_ATTEMPTS` | `5` | 1–20 |
| `LOGIN_LOCKOUT_MINUTES` | `15` | 1–1440 |
| `LOGIN_PREFIX_LIMIT_ENABLED` | `false` | Per-network login limit; turn on only once client addresses are verified |
| `LOGIN_PREFIX_FAILURE_LIMIT` | `20` | 1–10000 failed logins per network per 15 minutes |
| `DATABASE_URL` | none | Needed by all three endpoints (see `database-operations.md`) |

## Getting and using a bearer token

Start the backend (`uvicorn app.main:app --reload --port 8000`), then in another PowerShell:

```powershell
$base = "http://localhost:8000/api/v1/auth"

# 1. Register (once)
$body = @{ full_name = "Asha Rao"; email = "asha.rao@example.com"; password = "a-long-passphrase" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/register" -ContentType "application/json" -Body $body

# 2. Log in and keep the token in a variable
$login = @{ email = "asha.rao@example.com"; password = "a-long-passphrase" } | ConvertTo-Json
$token = (Invoke-RestMethod -Method Post -Uri "$base/login" -ContentType "application/json" -Body $login).access_token

# 3. Call a protected endpoint
Invoke-RestMethod -Uri "$base/me" -Headers @{ Authorization = "Bearer $token" }
```

Seed users from P-5 (for example `asha.rao@example.com`) sign in with `SakshamDemo@2026`.

In Swagger (http://localhost:8000/docs): call `POST /api/v1/auth/login`, copy
`access_token`, click **Authorize**, paste the token (without the word "Bearer"), then try
`GET /api/v1/auth/me`.

The token expires after 30 minutes; log in again to get a new one.

## Running the authentication tests

```powershell
# Without a database: password hashing, token rules, input validation, bearer handling
python -m pytest tests/test_security.py tests/test_auth_api.py

# Against PostgreSQL: registration, duplicates (including concurrent), login, lockout, /me, audit
$env:TEST_DATABASE_URL = "postgresql://sakshampay_owner:<owner-password>@localhost:5432/sakshampay_dev"
python -m pytest tests/test_auth_postgres.py
Remove-Item Env:TEST_DATABASE_URL
```

The tests use a lighter Argon2id cost to stay fast (`fast_password_hashing` fixture);
`test_production_hasher_is_argon2id_with_rfc9106_parameters` checks the real parameters.

## Known limitations (v1)

- Registration answers `409 EMAIL_ALREADY_REGISTERED`, which does reveal that an email has an
  account. Login does not.
- **Per-network limits are off by default.** P-1 requires login and Verify attempts to be
  limited "per account and IP prefix". Both per-network limits are implemented, but until
  `LOGIN_PREFIX_LIMIT_ENABLED` and `VERIFY_PREFIX_LIMIT_ENABLED` are turned on (after the
  proxy check), only the per-account limits are active. The account lockout can be
  triggered by someone who knows a user's email (a 15-minute denial of sign-in).
- With the per-network limit on, someone on a shared network (campus, mobile carrier NAT)
  can block sign-in for others on it for 15 minutes.
- A token stays valid until it expires (no revocation list); deactivating a user blocks their
  existing tokens because every request re-checks the user.
- Behind a proxy (Render), audit IP addresses are the proxy's unless Uvicorn is started with
  `--proxy-headers --forwarded-allow-ips=...`.
- The frontend keeps the token in `sessionStorage` (P-1 decision D12, implemented in P-8;
  see [`frontend-authentication.md`](frontend-authentication.md)).
