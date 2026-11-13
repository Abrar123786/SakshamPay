# SakshamPay database operations (P-5)

How to set up PostgreSQL on Windows, run migrations, load seed data and use the
repository layer. All commands are PowerShell and run from the `backend` folder with the
virtual environment active (`.\.venv\Scripts\Activate.ps1`).

## 1. Install and start PostgreSQL (Windows)

1. Install PostgreSQL 16 with the EDB installer from postgresql.org/download/windows.
   Keep the default port 5432 and note the password you set for the `postgres` user.
2. Make `psql` available in this PowerShell session (adjust the version folder if needed):

   ```powershell
   $env:Path += ";C:\Program Files\PostgreSQL\16\bin"
   psql --version
   ```

   To make it permanent: Start → "Edit the system environment variables" → Environment
   Variables → Path → add `C:\Program Files\PostgreSQL\16\bin`.
3. Check the service is running:

   ```powershell
   Get-Service postgresql*
   # if it is stopped (name may differ, e.g. postgresql-x64-16):
   Start-Service postgresql-x64-16
   ```

## 2. Create the database and roles

You can keep the single `sakshampay_dev` role from P-2 for local work. The recommended
setup, and the one needed for full audit protection (section 6), uses two roles:

| Role | Used by | Rights |
| --- | --- | --- |
| `sakshampay_owner` | Alembic migrations, PostgreSQL tests | owns the tables |
| `sakshampay_app` | the running backend and the seed script | read/write as needed; no DELETE anywhere; no UPDATE on audit logs or risk assessments; cannot disable triggers |

```powershell
psql -U postgres -h localhost
```

Then, inside `psql` (choose your own local passwords):

```sql
CREATE ROLE sakshampay_owner LOGIN PASSWORD 'choose-owner-password';
CREATE ROLE sakshampay_app   LOGIN PASSWORD 'choose-app-password';
CREATE DATABASE sakshampay_dev OWNER sakshampay_owner;
\c sakshampay_dev
ALTER SCHEMA public OWNER TO sakshampay_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
\q
```

If `sakshampay_dev` already exists from P-2, either use it as is (single-role setup) or
run `ALTER DATABASE sakshampay_dev OWNER TO sakshampay_owner;` before the `\c` line.

## 3. Configure `backend\.env`

Do not overwrite an existing `.env`. Open it with `notepad .env` and add or update:

```text
DATABASE_URL=postgresql://sakshampay_app:choose-app-password@localhost:5432/sakshampay_dev
IDENTIFIER_HASH_KEY=<paste a generated key>
```

Generate the key once (changing it later makes stored fingerprints unmatchable):

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Single-role setup: use the `sakshampay_dev` user in `DATABASE_URL` instead. Hosted
databases usually need `?sslmode=require` at the end of the URL.

## 4. Run migrations

Migrations run as the owner role. An environment variable set in the session takes
precedence over `.env`:

```powershell
$env:DATABASE_URL = "postgresql://sakshampay_owner:choose-owner-password@localhost:5432/sakshampay_dev"
alembic upgrade head        # create/upgrade the schema
alembic current             # should print 6c0d187b23c1 (head)
alembic history             # list migrations
Remove-Item Env:DATABASE_URL
```

Then grant the application role its rights (repeat after any migration that adds tables):

```powershell
$env:PGPASSWORD = "choose-owner-password"
psql -h localhost -U sakshampay_owner -d sakshampay_dev -v app_role=sakshampay_app -f scripts/grant_app_privileges.sql
Remove-Item Env:PGPASSWORD
```

Single-role setup: just run `alembic upgrade head` (it uses `DATABASE_URL` from `.env`)
and skip the grants.

| Migration | What it does |
| --- | --- |
| `4f58d3769176` create core tables | the six P-4 tables with all constraints and indexes |
| `6c0d187b23c1` protect append-only tables | triggers blocking UPDATE, DELETE and TRUNCATE on `audit_logs` and `risk_assessments` |

Rolling back (development only; `downgrade base` drops every table and its data):

```powershell
alembic downgrade -1        # remove the latest migration
alembic downgrade base      # remove everything
```

Creating a migration after changing a model:

```powershell
alembic revision --autogenerate -m "describe the change"
```

Always read the generated file before applying it. Check: table order, `ondelete`
behaviour, constraint names, server defaults, and that `downgrade()` reverses `upgrade()`.
Autogenerate can render a `%` in a CHECK constraint as `%%`; correct it (see the initial
migration's header).

## 5. Load development seed data

```powershell
python -m seeds.dev_seed
```

- Creates 3 fictional users (`asha.rao@example.com`, `vikram.iyer@example.com`,
  `meera.nair@example.com`), 7 beneficiaries, 18 transactions covering every lifecycle
  outcome, their risk assessments, alerts and audit events.
- Running it again adds nothing (users, beneficiaries and transactions are matched by
  email, identifier fingerprint and idempotency key).
- It refuses to run when `APP_ENV=production` or before `alembic upgrade head`, and it is
  never run automatically.
- Demo password for all seed users (usable once P-6 adds sign-in): `SakshamDemo@2026`.

Resetting a development database (audit rows cannot be deleted, so drop and recreate):

```powershell
$env:DATABASE_URL = "postgresql://sakshampay_owner:choose-owner-password@localhost:5432/sakshampay_dev"
alembic downgrade base
alembic upgrade head
Remove-Item Env:DATABASE_URL
# re-run the grants script (two-role setup), then:
python -m seeds.dev_seed
```

## 6. Audit protection: what it does and does not do

Three layers protect `audit_logs` (and `risk_assessments`):

1. The repositories have no update or delete methods.
2. The ORM refuses UPDATE and DELETE of these rows (P-4).
3. PostgreSQL triggers refuse UPDATE, DELETE and TRUNCATE, including `TRUNCATE ... CASCADE`
   from a parent table, whatever tool issues them (P-5).

Limits:

- The table owner can `DROP` or `DISABLE` a trigger, and a superuser can bypass triggers
  (`SET session_replication_role = replica`). That is why the application should connect as
  `sakshampay_app`, which does not own the tables and has no UPDATE/DELETE on them.
  Verified: the app role gets "permission denied" for UPDATE/DELETE, "must be owner" for
  DISABLE/DROP TRIGGER, and cannot change `session_replication_role`.
- `DROP TABLE` (as in `alembic downgrade base`) is not blocked: it is a schema change made
  by the owner, not ordinary data access.
- This is tamper-resistance against application bugs and ordinary access, not
  tamper-proofing against a database administrator. Stronger guarantees would need
  off-database copies (log shipping, write-once storage), which are out of scope.

## 7. Using the repositories (for later phases)

Repositories flush inside a savepoint and **never commit**; the caller owns the
transaction:

```python
from app.database.session import DbSession
from app.repositories import TransactionRepository, AuditLogRepository

def example(session: DbSession, user_id, beneficiary_id):
    transactions = TransactionRepository(session)
    audit = AuditLogRepository(session)
    result = transactions.create_idempotent(
        user_id=user_id, beneficiary_id=beneficiary_id, amount_paise=250_000,
        transaction_type="P2P", idempotency_key="...", request_hash="...",
    )
    if result.created:
        audit.record(action="TRANSACTION_INITIATED", actor_type="USER",
                     user_id=user_id, transaction_id=result.transaction.id)
    session.commit()  # both rows or neither
```

| Situation | What the repository raises (HTTP status when it reaches an endpoint) |
| --- | --- |
| Duplicate email / phone | `EmailAlreadyRegisteredError` / `PhoneAlreadyRegisteredError` (409) |
| Same payee saved twice | `DuplicateBeneficiaryError` (409) |
| Paying or alerting about another user's record | `BeneficiaryNotFoundError` / `TransactionNotFoundError` (404) |
| Idempotency-Key reused with a different request | `IdempotencyKeyReusedError` (409) |
| Same Idempotency-Key, same request (retry or double click) | no error: the original transaction is returned with `created=False` |
| Status change the P-1 lifecycle forbids | `InvalidStateTransitionError` (409) |
| Someone else changed the transaction first | `ConcurrentModificationError` (409) |
| Second assessment for a transaction | `AssessmentAlreadyExistsError` (409) |

Any other constraint violation is left as a database error (500), because it indicates a
bug rather than a user mistake.

## 8. Run the tests

```powershell
python -m pytest                       # no database needed; PostgreSQL suites are skipped

$env:TEST_DATABASE_URL = "postgresql://sakshampay_owner:choose-owner-password@localhost:5432/sakshampay_dev"
python -m pytest                       # everything, including PostgreSQL
Remove-Item Env:TEST_DATABASE_URL
```

The PostgreSQL tests migrate their own temporary schemas (`p5_test_...`) and drop them
afterwards, so they never touch your data. Use a role that may create schemas in the
database (the owner).

**Why no SQLite:** the schema relies on PostgreSQL features (UUID, JSONB and INET types,
regular-expression CHECK constraints, partial indexes, identity columns, PL/pgSQL
triggers). SQLite cannot create these tables, so SQLite tests would exercise a different
schema from the one deployed. Logic that needs no database is tested without one instead.

## 9. Production notes

- Run `alembic upgrade head` against the production database (as the owner role) before
  starting a new backend version, e.g. as Render's pre-deploy command if your plan offers
  it, or manually.
- Use the app role in the service's `DATABASE_URL` if your PostgreSQL host lets you create
  roles; otherwise the triggers still protect history from application code.
- Never run the seed script against production: it refuses when `APP_ENV=production`.

## 10. Time zones

All timestamp columns are `TIMESTAMP WITH TIME ZONE`, so PostgreSQL stores instants. What
it *returns* depends on the session `TimeZone`, which defaults to the server's setting
(an installer often picks the computer's zone, e.g. `Asia/Calcutta`). psycopg then hands
SQLAlchemy datetimes in that zone. To keep this from leaking into the application:

- every application connection sets `timezone=UTC` (`app/database/session.py`, next to
  `statement_timeout`); no query depends on the session zone, so this changes no result;
- every API response timestamp is a `UtcDateTime` (`app/schemas/common.py`) and is written
  in UTC with a `Z` suffix, keeping its microseconds, whatever zone it arrived in.

`tests/test_api_timestamps_postgres.py` forces an `Asia/Kolkata` session to prove the API
output is identical either way; `tests/test_api_timestamps.py` fails if a response field
is typed plain `datetime`.
