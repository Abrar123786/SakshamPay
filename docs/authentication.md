# SakshamPay authentication (P-6)

Email-and-password sign-in issuing short-lived JWT access tokens. Backend only; the
frontend screens come in a later phase. All commands are PowerShell, run from `backend`
with the virtual environment active.

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
| 503 | `AUTH_NOT_CONFIGURED` (no usable `JWT_SECRET_KEY`) or a database error |

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
- No per-IP rate limiting; the per-account lockout is the brute-force control. Lockout can be
  triggered by someone who knows a user's email (a 15-minute denial of sign-in).
- A token stays valid until it expires (no revocation list); deactivating a user blocks their
  existing tokens because every request re-checks the user.
- Behind a proxy (Render), audit IP addresses are the proxy's unless Uvicorn is started with
  `--proxy-headers --forwarded-allow-ips=...`.
- Tokens are meant to be kept in `sessionStorage` by the frontend (P-1 decision D12); that
  choice is implemented with the frontend screens.
