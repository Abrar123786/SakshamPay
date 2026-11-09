"""P-5: PostgreSQL connection, Alembic migrations, schema parity, audit triggers, readiness.

Runs only with TEST_DATABASE_URL (see tests/pg.py).
"""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from app.database.base import Base
from app.database.migrations import current_revision, head_revision, is_up_to_date
from app.database.session import Database
from app.main import create_app
from tests.conftest import UNREACHABLE_DATABASE_URL, make_settings
from tests.pg import database_for, require_postgres_url, run_alembic, throwaway_schema

PG_URL = require_postgres_url()

SIX_TABLES = {"users", "beneficiaries", "transactions", "risk_assessments", "alerts", "audit_logs"}
TRIGGERS = {
    "trg_audit_logs_block_update_delete",
    "trg_audit_logs_block_truncate",
    "trg_risk_assessments_block_update_delete",
    "trg_risk_assessments_block_truncate",
}


@pytest.fixture(scope="module")
def engine():
    with throwaway_schema(PG_URL) as engine:
        yield engine


def tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def triggers(engine) -> set[str]:
    with engine.connect() as connection:
        return set(connection.execute(text(
            "SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal AND c.relnamespace = current_schema()::regnamespace"
        )).scalars())


# 1. Connection ------------------------------------------------------------------------------

def test_postgresql_connection_through_p3_database_layer():
    database = Database(make_settings(DATABASE_URL=PG_URL))
    try:
        status = database.check_connection()
        assert status.state == "ok" and status.latency_ms is not None
        with database.engine.connect() as connection:
            assert connection.execute(text("SHOW statement_timeout")).scalar() == "3s"
            assert connection.execute(text("SELECT current_setting('application_name')")).scalar() == "SakshamPay"
    finally:
        database.dispose()


# 2-4. Migrations -------------------------------------------------------------------------------

def test_upgrade_creates_six_tables_and_reaches_head(engine):
    assert tables(engine) == SIX_TABLES | {"alembic_version"}
    with engine.connect() as connection:
        assert current_revision(connection) == head_revision()
        assert is_up_to_date(connection)


def test_migrated_schema_matches_models_exactly(engine):
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": True})
        assert compare_metadata(context, Base.metadata) == []


def test_upgrade_installs_append_only_triggers(engine):
    assert triggers(engine) == TRIGGERS


def test_downgrade_and_upgrade_round_trip():
    with throwaway_schema(PG_URL) as engine:
        run_alembic(engine, "downgrade", "-1")  # remove only the protection migration
        assert tables(engine) == SIX_TABLES | {"alembic_version"}
        assert triggers(engine) == set()

        run_alembic(engine, "downgrade", "base")
        assert tables(engine) == {"alembic_version"}
        with engine.connect() as connection:
            assert current_revision(connection) is None
            functions = connection.execute(text(
                "SELECT count(*) FROM pg_proc WHERE proname = 'prevent_append_only_modification' "
                "AND pronamespace = current_schema()::regnamespace"
            )).scalar()
            assert functions == 0

        run_alembic(engine, "upgrade", "head")
        assert tables(engine) == SIX_TABLES | {"alembic_version"}
        assert triggers(engine) == TRIGGERS


def test_unmigrated_schema_is_reported_as_not_up_to_date():
    with throwaway_schema(PG_URL, migrate=False) as engine, engine.connect() as connection:
        assert current_revision(connection) is None
        assert not is_up_to_date(connection)


# 10-11. Database-level audit protection ----------------------------------------------------------

def _insert_audit_row(connection) -> int:
    return connection.execute(text(
        "INSERT INTO audit_logs (actor_type, action) VALUES ('SYSTEM', 'PROBE_EVENT') RETURNING id"
    )).scalar()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_logs SET action = 'CHANGED_EVENT'",
        "DELETE FROM audit_logs",
        "TRUNCATE audit_logs",
        "TRUNCATE users CASCADE",  # cascading truncate from a parent must not wipe audit history
    ],
)
def test_raw_sql_cannot_modify_audit_history(engine, statement):
    with engine.connect() as connection:
        transaction = connection.begin()
        _insert_audit_row(connection)
        savepoint = connection.begin_nested()
        with pytest.raises(DBAPIError, match="append-only") as exc_info:
            connection.execute(text(statement))
        assert exc_info.value.orig.sqlstate == "42501"  # insufficient_privilege
        savepoint.rollback()
        assert connection.execute(text("SELECT count(*) FROM audit_logs WHERE action = 'PROBE_EVENT'")).scalar() == 1
        transaction.rollback()


@pytest.mark.parametrize("statement", ["UPDATE risk_assessments SET rule_score = 0", "DELETE FROM risk_assessments"])
def test_raw_sql_cannot_modify_risk_assessments(engine, statement):
    # The trigger fires per row, so the table needs a row: build the minimal chain.
    with engine.connect() as connection:
        transaction = connection.begin()
        user_id = connection.execute(text(
            "INSERT INTO users (full_name, email, password_hash) VALUES "
            "('Probe User', 'probe@example.com', '$argon2id$v=19$m=65536,t=3,p=4$' || repeat('a', 40)) RETURNING id"
        )).scalar()
        beneficiary_id = connection.execute(text(
            "INSERT INTO beneficiaries (user_id, beneficiary_name, upi_id_masked, upi_id_fingerprint) "
            "VALUES (:u, 'Probe Payee', 'pr****@demo', repeat('a', 64)) RETURNING id"
        ), {"u": user_id}).scalar()
        transaction_id = connection.execute(text(
            "INSERT INTO transactions (user_id, beneficiary_id, amount_paise, transaction_type, idempotency_key, "
            "request_hash, version) VALUES (:u, :b, 100, 'P2P', 'probe-key-1', repeat('b', 64), 1) RETURNING id"
        ), {"u": user_id, "b": beneficiary_id}).scalar()
        connection.execute(text(
            "INSERT INTO risk_assessments (transaction_id, rule_score, final_risk_score, risk_level, config_version, "
            "rule_details, explanation, features_snapshot, allowed_actions) "
            "VALUES (:t, 10, 10, 'MEDIUM', 'c1', '[]', '[]', '{}', '[\"CANCEL\"]')"
        ), {"t": transaction_id})
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(text(statement))
        transaction.rollback()


def test_inserts_into_protected_tables_still_work(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        assert _insert_audit_row(connection) > 0
        transaction.rollback()


# 14-15. Readiness -------------------------------------------------------------------------------------

def test_readiness_with_migrated_database_available(engine):
    app = create_app(make_settings(DATABASE_URL=PG_URL))
    app.state.database = database_for(engine)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["database"]["status"] == "ok"


def test_readiness_with_database_unavailable_is_503_and_safe():
    app = create_app(make_settings(DATABASE_URL=UNREACHABLE_DATABASE_URL, DB_CONNECT_TIMEOUT_SECONDS=1))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200  # liveness never depends on the database
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"]["status"] == "unavailable"
    assert "not-a-real-password" not in response.text and "127.0.0.1" not in response.text
