-- SakshamPay: least-privilege grants for the application role.
--
-- Run as the OWNER role (the one that runs `alembic upgrade head`), after every
-- migration that adds tables. Safe to run repeatedly.
--
--   psql -h localhost -U sakshampay_owner -d sakshampay_dev -v app_role=sakshampay_app -f scripts/grant_app_privileges.sql
--
-- Effect:
--   * the application can read and write what it needs, but has no DELETE anywhere
--     (financial history is never deleted) and no UPDATE on audit_logs or
--     risk_assessments (append-only);
--   * because the application role does not own the tables, it cannot DROP or
--     DISABLE the append-only triggers either.

\set ON_ERROR_STOP on

GRANT USAGE ON SCHEMA public TO :"app_role";

REVOKE ALL ON users, beneficiaries, transactions, risk_assessments, alerts, audit_logs, alembic_version FROM :"app_role";

GRANT SELECT, INSERT, UPDATE ON users, beneficiaries, transactions, alerts TO :"app_role";
GRANT SELECT, INSERT ON risk_assessments, audit_logs TO :"app_role";
GRANT SELECT ON alembic_version TO :"app_role";

-- audit_logs.id is an identity column backed by a sequence.
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO :"app_role";
