"""P-4 model definitions, checked from SQLAlchemy metadata (no PostgreSQL needed)."""

import itertools
import re
import warnings

import pytest
from sqlalchemy import BigInteger, Float, Integer, Numeric, SmallInteger
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable

import app.models as models
from app.models import Base, compute_final_risk_score
from app.models.common import assert_no_sensitive_keys

TABLES = {"users", "beneficiaries", "transactions", "risk_assessments", "alerts", "audit_logs"}
MODELS = {
    "users": models.User,
    "beneficiaries": models.Beneficiary,
    "transactions": models.Transaction,
    "risk_assessments": models.RiskAssessment,
    "alerts": models.Alert,
    "audit_logs": models.AuditLog,
}


def table(name):
    return Base.metadata.tables[name]


def ddl(name):
    """CREATE TABLE as PostgreSQL will receive it (naming convention applied)."""
    return str(CreateTable(table(name)).compile(dialect=postgresql.dialect()))


def constraint_names(name, kind):
    keyword = {"unique_constraint": "UNIQUE", "check_constraint": "CHECK"}[kind]
    return set(re.findall(rf"CONSTRAINT (\w+) {keyword} ", ddl(name)))


def check_sql(name, constraint):
    match = re.search(rf"CONSTRAINT {constraint} CHECK \((.*)\),? *$", ddl(name), re.MULTILINE)
    assert match, constraint
    return match.group(1)


def foreign_keys(name):
    """{(local columns): (referred table, referred columns, ondelete)}"""
    return {
        tuple(c.name for c in fk.columns): (
            fk.referred_table.name,
            tuple(e.column.name for e in fk.elements),
            fk.ondelete,
        )
        for fk in table(name).foreign_key_constraints
    }


# 1. Import and registration ------------------------------------------------------------

def test_all_six_models_import_and_map_to_their_tables():
    for table_name, model in MODELS.items():
        assert model.__tablename__ == table_name


def test_metadata_contains_exactly_the_six_tables():
    assert set(Base.metadata.tables) == TABLES


def test_mappers_configure_without_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        configure_mappers()


def test_postgresql_ddl_compiles_and_names_fit_63_chars():
    dialect = postgresql.dialect()
    for t in Base.metadata.sorted_tables:
        str(CreateTable(t).compile(dialect=dialect))
        for index in t.indexes:
            str(CreateIndex(index).compile(dialect=dialect))
        names = [c.name for c in t.constraints] + [i.name for i in t.indexes]
        assert all(n and len(n) <= 63 for n in names), t.name


# 2. Primary keys --------------------------------------------------------------------------

@pytest.mark.parametrize("table_name", sorted(TABLES - {"audit_logs"}))
def test_uuid_primary_keys(table_name):
    pk = list(table(table_name).primary_key.columns)
    assert [c.name for c in pk] == ["id"]
    assert isinstance(pk[0].type, UUID)
    assert pk[0].server_default.arg.text == "gen_random_uuid()"


def test_audit_log_primary_key_is_bigint_identity():
    pk = table("audit_logs").c.id
    assert pk.primary_key and isinstance(pk.type, BigInteger) and pk.identity is not None


# 3. Foreign keys -------------------------------------------------------------------------

def test_foreign_keys_and_targets():
    assert foreign_keys("beneficiaries") == {("user_id",): ("users", ("id",), "RESTRICT")}
    assert foreign_keys("transactions") == {
        ("user_id",): ("users", ("id",), "RESTRICT"),
        ("beneficiary_id", "user_id"): ("beneficiaries", ("id", "user_id"), "RESTRICT"),
    }
    assert foreign_keys("risk_assessments") == {("transaction_id",): ("transactions", ("id",), "RESTRICT")}
    assert foreign_keys("alerts") == {
        ("user_id",): ("users", ("id",), "RESTRICT"),
        ("transaction_id", "user_id"): ("transactions", ("id", "user_id"), "RESTRICT"),
        ("risk_assessment_id", "transaction_id"): ("risk_assessments", ("id", "transaction_id"), "RESTRICT"),
    }
    assert foreign_keys("audit_logs") == {
        ("user_id",): ("users", ("id",), "RESTRICT"),
        ("transaction_id",): ("transactions", ("id",), "RESTRICT"),
    }


def test_no_foreign_key_cascades_deletes_or_nulls():
    for t in Base.metadata.tables.values():
        for fk in t.foreign_key_constraints:
            assert fk.ondelete == "RESTRICT", f"{t.name}: {fk.name}"


def test_composite_fk_targets_are_backed_by_unique_constraints():
    assert "uq_beneficiaries_id_user_id" in constraint_names("beneficiaries", "unique_constraint")
    assert "uq_transactions_id_user_id" in constraint_names("transactions", "unique_constraint")
    assert "uq_risk_assessments_id_transaction_id" in constraint_names("risk_assessments", "unique_constraint")


@pytest.mark.parametrize(
    ("table_name", "column"),
    [
        ("beneficiaries", "user_id"),
        ("transactions", "user_id"),
        ("transactions", "beneficiary_id"),
        ("risk_assessments", "transaction_id"),
        ("alerts", "user_id"),
    ],
)
def test_ownership_columns_are_not_nullable(table_name, column):
    assert table(table_name).c[column].nullable is False


@pytest.mark.parametrize(
    ("table_name", "column"),
    [("alerts", "transaction_id"), ("alerts", "risk_assessment_id"), ("audit_logs", "user_id"), ("audit_logs", "transaction_id")],
)
def test_optional_links_are_nullable(table_name, column):
    assert table(table_name).c[column].nullable is True


# 4. Unique constraints -------------------------------------------------------------------

@pytest.mark.parametrize(
    ("table_name", "expected"),
    [
        ("users", {"uq_users_email", "uq_users_phone_number"}),
        (
            "beneficiaries",
            {
                "uq_beneficiaries_user_id_account_reference_fingerprint",
                "uq_beneficiaries_user_id_upi_id_fingerprint",
                "uq_beneficiaries_id_user_id",
            },
        ),
        ("transactions", {"uq_transactions_user_id_idempotency_key", "uq_transactions_id_user_id"}),
        ("risk_assessments", {"uq_risk_assessments_transaction_id", "uq_risk_assessments_id_transaction_id"}),
    ],
)
def test_unique_constraints(table_name, expected):
    assert constraint_names(table_name, "unique_constraint") == expected


# 5. Check constraints --------------------------------------------------------------------

EXPECTED_CHECKS = {
    "users": {
        "ck_users_email_lowercase",
        "ck_users_email_format",
        "ck_users_full_name_not_blank",
        "ck_users_phone_e164",
        "ck_users_password_hash_argon2id",
        "ck_users_failed_login_count_range",
    },
    "beneficiaries": {
        "ck_beneficiaries_has_payment_identifier",
        "ck_beneficiaries_account_reference_pair",
        "ck_beneficiaries_upi_id_pair",
        "ck_beneficiaries_account_fingerprint_hex",
        "ck_beneficiaries_upi_fingerprint_hex",
        "ck_beneficiaries_name_not_blank",
    },
    "transactions": {
        "ck_transactions_amount_positive",
        "ck_transactions_currency_inr",
        "ck_transactions_idempotency_key_length",
        "ck_transactions_request_hash_hex",
        "ck_transactions_device_id_hash_hex",
        "ck_transactions_verify_attempts_range",
        "ck_transactions_version_positive",
        "ck_transactions_analysed_at_required",
        "ck_transactions_completed_at_matches_status",
        "ck_transactions_approval_method_matches_status",
        "ck_transactions_expires_at_required",
        "ck_transactions_timestamps_ordered",
        "ck_transactions_transaction_type",
        "ck_transactions_status",
        "ck_transactions_approval_method",
    },
    "risk_assessments": {
        "ck_risk_assessments_rule_score_range",
        "ck_risk_assessments_ml_score_range",
        "ck_risk_assessments_final_risk_score_range",
        "ck_risk_assessments_final_score_formula",
        "ck_risk_assessments_model_version_matches_ml",
        "ck_risk_assessments_ml_details_matches_ml",
        "ck_risk_assessments_rule_details_array",
        "ck_risk_assessments_ml_details_object",
        "ck_risk_assessments_explanation_array",
        "ck_risk_assessments_features_snapshot_object",
        "ck_risk_assessments_allowed_actions_non_empty",
        "ck_risk_assessments_risk_level",
    },
    "alerts": {
        "ck_alerts_assessment_requires_transaction",
        "ck_alerts_read_at_matches_is_read",
        "ck_alerts_title_not_blank",
        "ck_alerts_message_not_blank",
        "ck_alerts_alert_type",
        "ck_alerts_severity",
    },
    "audit_logs": {
        "ck_audit_logs_action_format",
        "ck_audit_logs_entity_type_format",
        "ck_audit_logs_entity_pair",
        "ck_audit_logs_user_actor_has_user",
        "ck_audit_logs_old_values_object",
        "ck_audit_logs_new_values_object",
        "ck_audit_logs_metadata_object",
        "ck_audit_logs_actor_type",
    },
}


@pytest.mark.parametrize("table_name", sorted(TABLES))
def test_check_constraints(table_name):
    assert constraint_names(table_name, "check_constraint") == EXPECTED_CHECKS[table_name]


def test_status_check_lists_exactly_the_p1_lifecycle():
    sql = check_sql("transactions", "ck_transactions_status")
    for state in ("INITIATED", "ANALYSED", "AWAITING_USER_ACTION", "APPROVED", "CANCELLED", "EXPIRED", "FAILED"):
        assert f"'{state}'" in sql
    assert [s.value for s in models.TransactionStatus] == [
        "INITIATED", "ANALYSED", "AWAITING_USER_ACTION", "APPROVED", "CANCELLED", "EXPIRED", "FAILED",
    ]


def test_password_hash_must_be_argon2id():
    assert "$argon2id$" in check_sql("users", "ck_users_password_hash_argon2id")


# 6. Relationships ------------------------------------------------------------------------

EXPECTED_RELATIONSHIPS = {
    models.User: {"beneficiaries": ("Beneficiary", True), "transactions": ("Transaction", True), "alerts": ("Alert", True)},
    models.Beneficiary: {"user": ("User", False), "transactions": ("Transaction", True)},
    models.Transaction: {
        "user": ("User", False),
        "beneficiary": ("Beneficiary", False),
        "risk_assessment": ("RiskAssessment", False),
        "alerts": ("Alert", True),
    },
    models.RiskAssessment: {"transaction": ("Transaction", False), "alerts": ("Alert", True)},
    models.Alert: {
        "user": ("User", False),
        "transaction": ("Transaction", False),
        "risk_assessment": ("RiskAssessment", False),
    },
    models.AuditLog: {"user": ("User", False), "transaction": ("Transaction", False)},
}


@pytest.mark.parametrize("model", list(EXPECTED_RELATIONSHIPS), ids=lambda m: m.__name__)
def test_relationships(model):
    configure_mappers()
    relationships = model.__mapper__.relationships
    actual = {name: (rel.mapper.class_.__name__, rel.uselist) for name, rel in relationships.items()}
    assert actual == EXPECTED_RELATIONSHIPS[model]


def test_back_populates_are_symmetric():
    configure_mappers()
    for model in EXPECTED_RELATIONSHIPS:
        for name, rel in model.__mapper__.relationships.items():
            if rel.back_populates:
                partner = rel.mapper.relationships[rel.back_populates]
                assert partner.back_populates == name, f"{model.__name__}.{name}"


def test_no_relationship_cascades_deletes():
    configure_mappers()
    for model in EXPECTED_RELATIONSHIPS:
        for name, rel in model.__mapper__.relationships.items():
            assert "delete" not in rel.cascade, f"{model.__name__}.{name}"


# 7. Money ----------------------------------------------------------------------------------

def test_amount_is_bigint_paise():
    column = table("transactions").c.amount_paise
    assert isinstance(column.type, BigInteger) and not column.nullable
    assert table("transactions").c.currency.server_default.arg.text == "'INR'"


def test_no_floating_point_or_decimal_columns_anywhere():
    for t in Base.metadata.tables.values():
        for column in t.columns:
            assert not isinstance(column.type, (Float, Numeric)), f"{t.name}.{column.name}"


def test_timestamps_are_timezone_aware():
    for t in Base.metadata.tables.values():
        for column in t.columns:
            if column.name.endswith("_at") or column.name == "locked_until":
                assert column.type.timezone is True, f"{t.name}.{column.name}"


# 8. Risk scores ------------------------------------------------------------------------------

@pytest.mark.parametrize("column", ["rule_score", "ml_score", "final_risk_score"])
def test_scores_are_small_integers_with_0_to_100_checks(column):
    assert isinstance(table("risk_assessments").c[column].type, SmallInteger)
    assert "BETWEEN 0 AND 100" in check_sql("risk_assessments", f"ck_risk_assessments_{column}_range")


def test_ml_score_is_optional_but_rule_and_final_are_required():
    c = table("risk_assessments").c
    assert c.ml_score.nullable and not c.rule_score.nullable and not c.final_risk_score.nullable


def test_python_formula_matches_approved_weights_for_every_score_pair():
    for rule, ml in itertools.product(range(101), repeat=2):
        exact = 0.6 * rule + 0.4 * ml
        expected = int(exact + 0.5)  # exact is never x.5, so this is unambiguous rounding
        assert compute_final_risk_score(rule, ml) == expected
        assert 0 <= compute_final_risk_score(rule, ml) <= 100
    assert compute_final_risk_score(70, None) == 70  # rules-only fallback


def test_jsonb_columns_for_structured_details():
    for column in ("rule_details", "ml_details", "explanation", "features_snapshot", "allowed_actions"):
        assert isinstance(table("risk_assessments").c[column].type, JSONB)
    for column in ("old_values", "new_values", "metadata"):
        assert isinstance(table("audit_logs").c[column].type, JSONB)


def test_nullable_json_columns_store_python_none_as_sql_null():
    # Without none_as_null, None is written as the JSON value null, which breaks
    # "IS NULL" checks such as (ml_score IS NULL) = (ml_details IS NULL).
    for t in Base.metadata.tables.values():
        for column in t.columns:
            if isinstance(column.type, JSONB) and column.nullable:
                assert column.type.none_as_null, f"{t.name}.{column.name}"


# 9. Sensitive data and append-only ------------------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        {"password": "x"},
        {"user": {"Password_Hash": "x"}},
        {"items": [{"access-token": "x"}]},
        {"Authorization": "Bearer x"},
        {"jwt": "x"},
    ],
)
def test_audit_json_rejects_credentials(payload):
    with pytest.raises(ValueError, match="sensitive key"):
        models.AuditLog(actor_type=models.AuditActorType.SYSTEM, action="TEST_EVENT", event_metadata=payload)


def test_audit_json_accepts_normal_metadata():
    log = models.AuditLog(
        actor_type=models.AuditActorType.SYSTEM,
        action="TRANSACTION_STATUS_CHANGED",
        new_values={"status": "APPROVED", "approval_method": "CONTINUE"},
        user_agent="x" * 2000,
    )
    assert log.new_values["status"] == "APPROVED"
    assert len(log.user_agent) == 512


def test_risk_assessment_json_rejects_credentials():
    with pytest.raises(ValueError):
        models.RiskAssessment(features_snapshot={"otp": "123456"})


def test_sensitive_key_check_handles_nested_lists():
    assert_no_sensitive_keys([{"ok": [{"also_ok": 1}]}], "x")


def test_user_repr_never_shows_password_hash():
    user = models.User(email="a@example.com", full_name="A", password_hash="$argon2id$secret-material")
    assert "argon2id" not in repr(user)
