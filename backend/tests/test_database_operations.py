"""P-5 logic that needs no database: privacy helpers, lifecycle table, error
translation, migration files and seed definitions."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import BACKEND_DIR, Settings
from app.models import ApprovalMethod, RiskLevel, TransactionStatus, compute_final_risk_score
from app.repositories import ALLOWED_TRANSITIONS
from app.repositories.base import MAX_PAGE_SIZE, clamp_limit, clamp_offset
from app.utils.privacy import (
    IdentifierKeyMissingError,
    InvalidIdentifierError,
    hash_device_id,
    identifier_key,
    protect_account_reference,
    protect_upi_id,
    truncate_ip_address,
)
from seeds import dev_seed
from tests.conftest import make_production_settings, make_settings

KEY = b"unit-test-key-0123456789abcdef0123"
S = TransactionStatus


# ---- privacy helpers ------------------------------------------------------------------------

def test_account_reference_is_normalised_masked_and_fingerprinted():
    a = protect_account_reference("0001 2345-6789", KEY)
    b = protect_account_reference("000123456789", KEY)
    assert a == b
    assert a.masked == "XXXXXXXX6789"
    assert re.fullmatch(r"[0-9a-f]{64}", a.fingerprint)
    assert "000123456789" not in a.fingerprint


def test_upi_id_is_case_insensitive_and_masked():
    a = protect_upi_id(" Ravi.Kumar@OKDemo ", KEY)
    assert a == protect_upi_id("ravi.kumar@okdemo", KEY)
    assert a.masked == "ra****@okdemo"


def test_fingerprints_depend_on_the_key_and_the_kind():
    assert protect_upi_id("ab@demo", KEY).fingerprint != protect_upi_id("ab@demo", b"another-key-entirely-0123456789").fingerprint
    assert hash_device_id("ab@demo", KEY) != protect_upi_id("ab@demo", KEY).fingerprint  # domain separation


@pytest.mark.parametrize("bad", ["12345", "ACCT#1234567", "x" * 40])
def test_invalid_account_references_are_rejected(bad):
    with pytest.raises(InvalidIdentifierError):
        protect_account_reference(bad, KEY)


@pytest.mark.parametrize("bad", ["no-at-sign", "@handle", "name@", "name@1bad", "a b@demo"])
def test_invalid_upi_ids_are_rejected(bad):
    with pytest.raises(InvalidIdentifierError):
        protect_upi_id(bad, KEY)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("203.0.113.57", "203.0.113.0/24"),
        ("2001:db8:abcd:12::1", "2001:db8:abcd::/48"),
        ("::ffff:203.0.113.57", "203.0.113.0/24"),  # IPv4-mapped: the IPv4 network, never '::/48'
        ("::ffff:198.51.100.9", "198.51.100.0/24"),
        ("::1", "::/48"),
        ("not-an-ip", None),
        (None, None),
    ],
)
def test_ip_addresses_are_truncated(raw, expected):
    assert truncate_ip_address(raw) == expected


def test_identifier_key_comes_from_settings():
    with pytest.raises(IdentifierKeyMissingError):
        identifier_key(make_settings())
    assert identifier_key(make_settings(IDENTIFIER_HASH_KEY="k" * 32)) == b"k" * 32


def test_identifier_key_is_secret_and_required_in_production():
    settings = make_production_settings()
    assert "i" * 48 not in repr(settings) and settings.safe_summary()["identifier_hash_key_configured"] is True
    with pytest.raises(ValidationError, match="IDENTIFIER_HASH_KEY"):
        make_production_settings(IDENTIFIER_HASH_KEY="")


def test_pool_recycle_setting():
    assert make_settings().DB_POOL_RECYCLE_SECONDS == 1800
    with pytest.raises(ValidationError):
        make_settings(DB_POOL_RECYCLE_SECONDS=10)


# ---- lifecycle table matches P-1 ------------------------------------------------------------------

def test_allowed_transitions_match_p1_lifecycle():
    assert ALLOWED_TRANSITIONS == {
        S.INITIATED: {S.ANALYSED, S.FAILED},
        S.ANALYSED: {S.AWAITING_USER_ACTION},
        S.AWAITING_USER_ACTION: {S.APPROVED, S.CANCELLED, S.EXPIRED},
        S.APPROVED: set(),
        S.CANCELLED: set(),
        S.EXPIRED: set(),
        S.FAILED: set(),
    }


def test_page_limits_are_clamped():
    assert clamp_limit(None) == 20 and clamp_limit(0) == 1 and clamp_limit(10_000) == MAX_PAGE_SIZE
    assert clamp_offset(-5) == 0 and clamp_offset(None) == 0


# ---- migration files ----------------------------------------------------------------------------------

MIGRATIONS = sorted((BACKEND_DIR / "migrations" / "versions").glob("*.py"))


def test_two_linear_migrations_exist():
    texts = [p.read_text() for p in MIGRATIONS]
    assert len(MIGRATIONS) == 2
    assert 'down_revision: Union[str, Sequence[str], None] = None' in texts[0]
    assert 'down_revision: str | Sequence[str] | None = "4f58d3769176"' in texts[1]


def test_initial_migration_creates_all_six_tables_and_downgrades():
    source = MIGRATIONS[0].read_text()
    for table in ("users", "beneficiaries", "transactions", "risk_assessments", "alerts", "audit_logs"):
        assert f"op.create_table('{table}'" in source
        assert f"op.drop_table('{table}')" in source
    assert "ondelete='CASCADE'" not in source and "ondelete='SET NULL'" not in source
    assert "'$argon2id$%%'" not in source  # the autogenerate escaping issue stays fixed


def test_protection_migration_covers_update_delete_and_truncate():
    source = MIGRATIONS[1].read_text()
    assert 'PROTECTED_TABLES = ("audit_logs", "risk_assessments")' in source
    assert "BEFORE UPDATE OR DELETE" in source and "BEFORE TRUNCATE" in source
    assert "DROP FUNCTION IF EXISTS" in source


def test_no_create_all_outside_tests():
    for path in list((BACKEND_DIR / "app").rglob("*.py")) + list((BACKEND_DIR / "seeds").rglob("*.py")):
        assert "create_all(" not in path.read_text(), path


# ---- seed definitions ---------------------------------------------------------------------------------

def test_seed_refuses_production_before_touching_the_database():
    production = make_production_settings()
    with pytest.raises(dev_seed.SeedRefused):
        dev_seed.seed_development_data(session=None, settings=production)
    with pytest.raises(dev_seed.SeedRefused):
        dev_seed.run(production)


def test_seed_cli_exits_2_in_production(monkeypatch, capsys):
    monkeypatch.setattr(dev_seed, "get_settings", make_production_settings)
    assert dev_seed.main([]) == 2
    assert "Refusing to seed" in capsys.readouterr().err


def test_seed_definitions_are_fictional_and_consistent():
    assert all(u.email.endswith("@example.com") for u in dev_seed.USERS)
    assert len({t.key for t in dev_seed.TRANSACTIONS}) == len(dev_seed.TRANSACTIONS)
    beneficiary_owner = {b.key: b.user for b in dev_seed.BENEFICIARIES}
    for spec in dev_seed.TRANSACTIONS:
        assert beneficiary_owner[spec.beneficiary] == spec.user  # never another user's payee
        if spec.outcome == S.APPROVED:
            rule = min(100, sum(dev_seed.RULES[r][0] for r in spec.rules))
            level = dev_seed.risk_level_for(compute_final_risk_score(rule, spec.ml_score), spec.ml_score is not None)
            needed = "VERIFY" if spec.approval == ApprovalMethod.VERIFIED else "CONTINUE"
            assert needed in dev_seed.ALLOWED_ACTIONS[level], spec.key


def test_seed_rule_points_are_the_unchanged_p1_weights():
    assert {k: v[0] for k, v in dev_seed.RULES.items()} == {"R1": 20, "R2": 25, "R3": 20, "R4": 10, "R5": 15, "R6": 15}


def test_seed_risk_bands():
    assert dev_seed.risk_level_for(30, True) == RiskLevel.LOW
    assert dev_seed.risk_level_for(31, True) == RiskLevel.MEDIUM
    assert dev_seed.risk_level_for(66, True) == RiskLevel.HIGH
    assert dev_seed.risk_level_for(10, False) == RiskLevel.MEDIUM  # fail-cautious without ML


def test_demo_password_hash_is_argon2id():
    assert dev_seed.DEMO_PASSWORD_HASH.startswith("$argon2id$")


def test_env_example_documents_p5_settings():
    example = (BACKEND_DIR / ".env.example").read_text()
    for name in ("DATABASE_URL", "DB_POOL_RECYCLE_SECONDS", "IDENTIFIER_HASH_KEY", "DB_POOL_SIZE"):
        assert re.search(rf"^#?\s*{name}=", example, re.MULTILINE), name
    assert Path(BACKEND_DIR / ".env.example").exists()
