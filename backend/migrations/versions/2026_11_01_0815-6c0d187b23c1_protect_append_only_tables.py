"""protect append-only tables

Database-level protection for audit history (and for risk assessments, which P-4
also defined as immutable records):

  * BEFORE UPDATE OR DELETE ... FOR EACH ROW  -> raises, so no row can change or vanish
  * BEFORE TRUNCATE ... FOR EACH STATEMENT    -> raises, so the table cannot be emptied
    (this also stops TRUNCATE ... CASCADE from a parent table)

INSERT and SELECT are unaffected. The application ORM already refuses these
operations (P-4); this adds a guard that also covers raw SQL, admin tools and bugs.

Limitations (see docs/database-operations.md):
  * The table owner can DROP or DISABLE the trigger, and a superuser can bypass
    triggers with ``SET session_replication_role = replica``. The application
    should therefore connect as a role that does NOT own the tables and has only
    SELECT/INSERT on these two tables; migrations run as the owner role.
  * This is tamper-resistance against application mistakes and ordinary access,
    not tamper-proofing against a database administrator.

Revision ID: 6c0d187b23c1
Revises: 4f58d3769176
Create Date: 2026-11-01 08:15:12.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "6c0d187b23c1"
down_revision: str | Sequence[str] | None = "4f58d3769176"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROTECTED_TABLES = ("audit_logs", "risk_assessments")
FUNCTION_NAME = "prevent_append_only_modification"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {FUNCTION_NAME}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% on table "%" is not allowed: records are append-only', TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'insufficient_privilege',
                      HINT = 'Insert a new record instead of changing or deleting an existing one.';
        END;
        $$;
        """
    )
    for table in PROTECTED_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_block_update_delete "
            f"BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {FUNCTION_NAME}()"
        )
        op.execute(
            f"CREATE TRIGGER trg_{table}_block_truncate "
            f"BEFORE TRUNCATE ON {table} "
            f"FOR EACH STATEMENT EXECUTE FUNCTION {FUNCTION_NAME}()"
        )


def downgrade() -> None:
    for table in PROTECTED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_block_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_block_update_delete ON {table}")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_NAME}()")
