"""P-5: development seed data against migrated PostgreSQL (TEST_DATABASE_URL only)."""

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Alert, AuditLog, Beneficiary, RiskAssessment, Transaction, TransactionStatus, User
from app.models.risk_assessment import compute_final_risk_score
from seeds import dev_seed
from tests.pg import require_postgres_url, settings_for, throwaway_schema

PG_URL = require_postgres_url()
MODELS = (User, Beneficiary, Transaction, RiskAssessment, Alert, AuditLog)


def counts(session) -> dict[str, int]:
    return {m.__tablename__: session.scalar(select(func.count()).select_from(m)) for m in MODELS}


@pytest.fixture
def engine():
    with throwaway_schema(PG_URL) as engine:
        yield engine


def seed(engine):
    with Session(engine) as session:
        report = dev_seed.seed_development_data(session, settings_for(PG_URL))
        session.commit()
        return report


def test_seed_creates_every_kind_of_record(engine):
    report = seed(engine)
    with Session(engine) as session:
        c = counts(session)
        assert c["users"] == 3 and c["beneficiaries"] == 7 and c["transactions"] == 18
        assert c["risk_assessments"] == 17  # the FAILED transaction never got an assessment
        assert c["alerts"] > 0 and c["audit_logs"] > 0
        statuses = set(session.scalars(select(Transaction.status)))
        assert statuses == set(TransactionStatus) - {TransactionStatus.INITIATED, TransactionStatus.ANALYSED}
    assert report.created["transactions"] == 18


def test_seed_is_repeatable_without_duplicates(engine):
    seed(engine)
    with Session(engine) as session:
        first = counts(session)
    second_report = seed(engine)
    with Session(engine) as session:
        assert counts(session) == first
    assert second_report.created == {}
    assert second_report.existing == {"users": 3, "beneficiaries": 7, "transactions": 18}


def test_seed_data_is_consistent_and_fictional(engine):
    seed(engine)
    with Session(engine) as session:
        for assessment in session.scalars(select(RiskAssessment)):
            assert assessment.final_risk_score == compute_final_risk_score(assessment.rule_score, assessment.ml_score)
        for user in session.scalars(select(User)):
            assert user.email.endswith("@example.com") and user.phone_number is None
        # only masked identifiers are stored
        raw = " ".join(session.execute(text(
            "SELECT coalesce(account_reference_masked, '') || ' ' || coalesce(upi_id_masked, '') FROM beneficiaries"
        )).scalars())
        assert "000123456789" not in raw and "ravi.kumar@" not in raw
        for txn in session.scalars(select(Transaction).where(Transaction.status == TransactionStatus.APPROVED)):
            assessment = session.scalar(select(RiskAssessment).where(RiskAssessment.transaction_id == txn.id))
            needed = "VERIFY" if txn.approval_method == "VERIFIED" else "CONTINUE"
            assert needed in assessment.allowed_actions


def test_seed_refuses_production(engine):
    production = settings_for(PG_URL).model_copy(update={"APP_ENV": "production"})
    with Session(engine) as session, pytest.raises(dev_seed.SeedRefused):
        dev_seed.seed_development_data(session, production)
    with Session(engine) as session:
        assert counts(session)["users"] == 0


def test_seed_is_all_or_nothing(engine, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("failure half-way through seeding")

    monkeypatch.setattr(dev_seed, "_play_lifecycle", explode)
    with Session(engine) as session:
        with pytest.raises(RuntimeError):
            dev_seed.seed_development_data(session, settings_for(PG_URL))
        session.rollback()
    with Session(engine) as session:
        assert counts(session) == {m.__tablename__: 0 for m in MODELS}
