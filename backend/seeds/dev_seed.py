"""Development seed data for SakshamPay.

    python -m seeds.dev_seed            (run from backend/, after `alembic upgrade head`)

What it creates: 3 fictional users, 7 fictional beneficiaries, 18 simulated
transactions covering every lifecycle outcome, their risk assessments, alerts and
audit events. Everything goes through the repositories, so it obeys the same
rules as application code (idempotency, lifecycle, ownership).

Safety:
  * refuses to run when APP_ENV=production (and is never run automatically);
  * refuses to run before migrations are at head;
  * repeatable: users, beneficiaries and transactions are looked up by natural key
    (email, identifier fingerprint, idempotency key) and skipped when present;
  * all-or-nothing: one database transaction, committed at the end.

Fictional data only: names are invented, emails use the reserved example.com
domain, account numbers and UPI IDs are made up and stored masked and fingerprinted,
banks are fictional. Scores are hand-written sample values that follow the approved
formula; they are not produced by the (not yet built) fraud engine.
"""

import argparse
import hashlib
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database.migrations import head_revision, is_up_to_date
from app.database.session import Database
from app.models import (
    AlertSeverity,
    AlertType,
    ApprovalMethod,
    AuditActorType,
    RiskLevel,
    TransactionStatus,
    TransactionType,
    compute_final_risk_score,
)
from app.repositories import (
    AlertRepository,
    AuditLogRepository,
    BeneficiaryRepository,
    RiskAssessmentRepository,
    TransactionRepository,
    UserRepository,
)
from app.utils.privacy import identifier_key, protect_account_reference, protect_upi_id

SEED_VERSION = "dev-seed-v1"
SEED_CONFIG_VERSION = "seed-risk-config-v1"
SEED_MODEL_VERSION = "seed-iforest-v0"
# Argon2id hash of the shared demo password "SakshamDemo@2026" (development only;
# generated once with argon2-cffi so the seed needs no hashing code).
DEMO_PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$LFoEaEEOXDNyF2Q8/0LUJg$vEnZE6Xfmlay/R84MJg5bYQp16ltLfWS4uwl2m3Al14"
IST = timedelta(hours=5, minutes=30)

# P-1 rules and their points (unchanged; they total 105, see the P-4 report).
RULES = {
    "R1": (20, "NEW_BENEFICIARY", "First payment to this beneficiary"),
    "R2": (25, "UNUSUAL_AMOUNT", "Amount is far above your usual payments"),
    "R3": (20, "HIGH_VELOCITY", "Several payments in a short time"),
    "R4": (10, "UNUSUAL_TIME", "You rarely pay at this time of day"),
    "R5": (15, "NEW_DEVICE", "First payment from this device"),
    "R6": (15, "BEHAVIOUR_DEVIATION", "Large first payment to a new payee"),
}
ALLOWED_ACTIONS = {
    RiskLevel.LOW: ["CONTINUE", "CANCEL"],
    RiskLevel.MEDIUM: ["CONTINUE", "VERIFY", "CANCEL"],
    RiskLevel.HIGH: ["VERIFY", "CANCEL"],
}


class SeedRefused(RuntimeError):
    pass


# ---- seed definitions -------------------------------------------------------------------

@dataclass(frozen=True)
class SeedUser:
    key: str
    full_name: str
    email: str


@dataclass(frozen=True)
class SeedBeneficiary:
    key: str
    user: str
    name: str
    bank: str | None = None
    account: str | None = None
    upi: str | None = None
    verified: bool = False


@dataclass(frozen=True)
class SeedTransaction:
    key: str
    user: str
    beneficiary: str
    rupees: int
    days_ago: float
    hour_ist: float  # 9.5 = 09:30 IST
    outcome: TransactionStatus
    rules: tuple[str, ...] = ()
    ml_score: int | None = 8
    approval: ApprovalMethod | None = None
    type: TransactionType = TransactionType.P2P
    note: str | None = None
    extra: dict = field(default_factory=dict)


USERS = [
    SeedUser("asha", "Asha Rao", "asha.rao@example.com"),
    SeedUser("vikram", "Vikram Iyer", "vikram.iyer@example.com"),
    SeedUser("meera", "Meera Nair", "meera.nair@example.com"),
]

BENEFICIARIES = [
    SeedBeneficiary("asha-ravi", "asha", "Ravi Kumar", upi="ravi.kumar@sakshamdemo", verified=True),
    SeedBeneficiary("asha-grocer", "asha", "Green Basket Grocers", upi="greenbasket@sakshamdemo", verified=True),
    SeedBeneficiary("asha-landlord", "asha", "Suresh Menon", bank="Demo Co-operative Bank", account="000123456789", verified=True),
    SeedBeneficiary("asha-unknown", "asha", "Quick Refund Desk", bank="Demo National Bank", account="998877665544"),
    SeedBeneficiary("vikram-priya", "vikram", "Priya Shah", upi="priya.shah@sakshamdemo", verified=True),
    SeedBeneficiary("vikram-electric", "vikram", "City Power Demo", bank="Demo National Bank", account="550011223344", verified=True),
    SeedBeneficiary("meera-tutor", "meera", "Anil Joseph", upi="anil.tutor@sakshamdemo"),
]

S = TransactionStatus
T = SeedTransaction
TRANSACTIONS = [
    # Asha: a normal month, then a scam-like attempt she cancels
    T("seed-asha-001", "asha", "asha-grocer", 1_850, 27, 18, S.APPROVED, ml_score=6, approval=ApprovalMethod.CONTINUE, type=TransactionType.P2M, note="Groceries"),
    T("seed-asha-002", "asha", "asha-ravi", 2_500, 24, 20, S.APPROVED, ml_score=12, approval=ApprovalMethod.CONTINUE, note="Dinner split"),
    T("seed-asha-003", "asha", "asha-landlord", 22_000, 21, 10, S.APPROVED, ml_score=18, approval=ApprovalMethod.CONTINUE, note="Rent"),
    T("seed-asha-004", "asha", "asha-grocer", 2_240, 17, 19, S.APPROVED, ml_score=5, approval=ApprovalMethod.CONTINUE, type=TransactionType.P2M),
    T("seed-asha-005", "asha", "asha-ravi", 900, 13, 21, S.APPROVED, ml_score=9, approval=ApprovalMethod.CONTINUE),
    T("seed-asha-006", "asha", "asha-grocer", 3_100, 9, 18, S.APPROVED, rules=("R4",), ml_score=22, approval=ApprovalMethod.CONTINUE, type=TransactionType.P2M),
    T("seed-asha-007", "asha", "asha-unknown", 48_000, 4, 2, S.CANCELLED, rules=("R1", "R2", "R4", "R6"), ml_score=82, note="Refund processing fee"),
    T("seed-asha-008", "asha", "asha-ravi", 12_000, 2, 22, S.APPROVED, rules=("R2", "R4"), ml_score=55, approval=ApprovalMethod.CONTINUE),
    T("seed-asha-009", "asha", "asha-unknown", 15_000, 1, 1, S.EXPIRED, rules=("R2", "R4", "R5"), ml_score=61),
    T("seed-asha-010", "asha", "asha-landlord", 22_000, 0.002, 11, S.AWAITING_USER_ACTION, rules=("R5",), ml_score=14, note="Rent"),
    # Vikram: steady bills, one verified high-value payment, one failed attempt
    T("seed-vikram-001", "vikram", "vikram-electric", 1_420, 26, 9, S.APPROVED, ml_score=4, approval=ApprovalMethod.CONTINUE, type=TransactionType.P2M),
    T("seed-vikram-002", "vikram", "vikram-priya", 5_000, 19, 13, S.APPROVED, ml_score=15, approval=ApprovalMethod.CONTINUE),
    T("seed-vikram-003", "vikram", "vikram-priya", 60_000, 11, 15, S.APPROVED, rules=("R2", "R3", "R5"), ml_score=88, approval=ApprovalMethod.VERIFIED, note="Wedding gift"),
    T("seed-vikram-004", "vikram", "vikram-electric", 1_510, 6, 9, S.FAILED, type=TransactionType.P2M),
    T("seed-vikram-005", "vikram", "vikram-electric", 1_510, 6, 9.1, S.APPROVED, ml_score=None, approval=ApprovalMethod.CONTINUE, type=TransactionType.P2M, note="Retry after failure"),
    # Meera: new user (cold start) paying a new tutor
    T("seed-meera-001", "meera", "meera-tutor", 3_000, 5, 17, S.APPROVED, rules=("R1",), ml_score=35, approval=ApprovalMethod.CONTINUE, note="Tuition"),
    T("seed-meera-002", "meera", "meera-tutor", 3_000, 3, 17, S.CANCELLED, rules=("R3",), ml_score=40, note="Duplicate tap"),
    T("seed-meera-003", "meera", "meera-tutor", 3_000, 0.5, 17, S.APPROVED, ml_score=10, approval=ApprovalMethod.CONTINUE, note="Tuition"),
]


# ---- helpers --------------------------------------------------------------------------------

def risk_level_for(final_score: int, ml_available: bool) -> RiskLevel:
    """Initial P-1 bands; LOW is raised to MEDIUM when the model was unavailable."""
    level = RiskLevel.LOW if final_score <= 30 else RiskLevel.MEDIUM if final_score <= 65 else RiskLevel.HIGH
    if not ml_available and level == RiskLevel.LOW:
        return RiskLevel.MEDIUM
    return level


def _request_hash(spec: SeedTransaction) -> str:
    payload = f"{spec.beneficiary}|{spec.rupees}|{spec.type}|{spec.note or ''}"
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class SeedReport:
    created: dict[str, int] = field(default_factory=dict)
    existing: dict[str, int] = field(default_factory=dict)

    def add(self, kind: str, created: bool) -> None:
        bucket = self.created if created else self.existing
        bucket[kind] = bucket.get(kind, 0) + 1


# ---- seeding ----------------------------------------------------------------------------------

def seed_development_data(session: Session, settings: Settings, *, now: datetime | None = None) -> SeedReport:
    """Insert seed rows that are missing. Does not commit: the caller decides."""
    if settings.is_production:
        raise SeedRefused("Seed data is for development only; APP_ENV is production.")
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    key = identifier_key(settings)
    report = SeedReport()

    users_repo = UserRepository(session)
    beneficiaries_repo = BeneficiaryRepository(session)
    transactions_repo = TransactionRepository(session)
    assessments_repo = RiskAssessmentRepository(session)
    alerts_repo = AlertRepository(session)
    audit_repo = AuditLogRepository(session)

    users = {}
    for spec in USERS:
        user = users_repo.get_by_email(spec.email)
        created = user is None
        if created:
            user = users_repo.create(full_name=spec.full_name, email=spec.email, password_hash=DEMO_PASSWORD_HASH)
            audit_repo.record(action="USER_CREATED", actor_type=AuditActorType.SYSTEM, user_id=user.id,
                              entity_type="user", entity_id=user.id, metadata={"source": SEED_VERSION})
        users[spec.key] = user
        report.add("users", created)

    beneficiaries = {}
    for spec in BENEFICIARIES:
        user = users[spec.user]
        account = protect_account_reference(spec.account, key) if spec.account else None
        upi = protect_upi_id(spec.upi, key) if spec.upi else None
        beneficiary = beneficiaries_repo.find_by_identifier(user.id, account=account, upi=upi)
        created = beneficiary is None
        if created:
            beneficiary = beneficiaries_repo.create(user_id=user.id, beneficiary_name=spec.name, bank_name=spec.bank,
                                                    account=account, upi=upi, is_verified=spec.verified)
            audit_repo.record(action="BENEFICIARY_ADDED", actor_type=AuditActorType.USER, user_id=user.id,
                              entity_type="beneficiary", entity_id=beneficiary.id, metadata={"source": SEED_VERSION})
        beneficiaries[spec.key] = beneficiary
        report.add("beneficiaries", created)

    for spec in TRANSACTIONS:
        user, beneficiary = users[spec.user], beneficiaries[spec.beneficiary]
        day = (now + IST - timedelta(days=spec.days_ago)).date()
        hour, minute = int(spec.hour_ist), int(round((spec.hour_ist % 1) * 60))
        initiated = datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC) - IST
        if spec.days_ago < 0.01:  # the "live" example: a couple of minutes ago
            initiated = now - timedelta(minutes=2)
        while initiated > now - timedelta(minutes=15) and spec.days_ago >= 0.01:
            initiated -= timedelta(days=1)  # never place history in the future
        result = transactions_repo.create_idempotent(
            user_id=user.id, beneficiary_id=beneficiary.id, amount_paise=spec.rupees * 100,
            transaction_type=spec.type, idempotency_key=spec.key, request_hash=_request_hash(spec),
            description=spec.note, initiated_at=initiated,
        )
        report.add("transactions", result.created)
        if not result.created:
            continue
        _play_lifecycle(spec, result.transaction, initiated, transactions_repo, assessments_repo, alerts_repo, audit_repo, report)

    if not audit_repo.exists_with_request_id(f"seed:{SEED_VERSION}"):
        audit_repo.record(action="SEED_DATA_LOADED", actor_type=AuditActorType.SYSTEM,
                          metadata={"seed_version": SEED_VERSION, "created": report.created},
                          request_id=f"seed:{SEED_VERSION}")
    return report


def _play_lifecycle(spec, txn, initiated, transactions_repo, assessments_repo, alerts_repo, audit_repo, report):
    """Walk one transaction through the P-1 lifecycle, recording what a real run would."""
    system_actions = {"TRANSACTION_ASSESSED", "TRANSACTION_EXPIRED", "TRANSACTION_FAILED"}

    def audit(action, old=None, new=None, at=None):
        actor = AuditActorType.SYSTEM if action in system_actions else AuditActorType.USER
        audit_repo.record(action=action, actor_type=actor,
                          user_id=txn.user_id, transaction_id=txn.id, entity_type="transaction", entity_id=txn.id,
                          old_values=old, new_values=new,
                          metadata={"source": SEED_VERSION, "occurred_at": (at or initiated).isoformat()})
        report.add("audit_logs", True)

    audit("TRANSACTION_INITIATED", new={"status": "INITIATED", "amount_paise": txn.amount_paise})

    if spec.outcome == S.FAILED:
        failed_at = initiated + timedelta(seconds=4)
        transactions_repo.transition(txn, S.FAILED, at=failed_at)
        audit("TRANSACTION_FAILED", {"status": "INITIATED"}, {"status": "FAILED", "reason": "assessment_timeout"}, failed_at)
        alerts_repo.create(user_id=txn.user_id, transaction_id=txn.id, alert_type=AlertType.TRANSACTION_FAILED,
                           severity=AlertSeverity.INFO, title="Payment not sent",
                           message="We could not assess this payment, so it was not sent. Nothing was paid.",
                           created_at=failed_at)
        report.add("alerts", True)
        return

    points = [RULES[r][0] for r in spec.rules]
    rule_score = min(100, sum(points))
    final = compute_final_risk_score(rule_score, spec.ml_score)
    level = risk_level_for(final, spec.ml_score is not None)
    analysed = initiated + timedelta(seconds=1)
    explanation = [{"code": RULES[r][1], "source": "rule", "label": RULES[r][2], "points": RULES[r][0]} for r in spec.rules]
    if spec.ml_score is not None and spec.ml_score >= 50:
        explanation.append({"code": "UNUSUAL_PATTERN", "source": "ml", "label": "This payment is unlike your usual activity", "points": None})
    if spec.ml_score is None:
        explanation.append({"code": "LIMITED_ASSESSMENT", "source": "system", "label": "Assessed with rules only; behaviour model unavailable", "points": None})

    assessment = assessments_repo.create(
        txn, rule_score=rule_score, ml_score=spec.ml_score, risk_level=level, config_version=SEED_CONFIG_VERSION,
        model_version=SEED_MODEL_VERSION if spec.ml_score is not None else None,
        rule_details=[{"rule": r, "code": RULES[r][1], "points": RULES[r][0]} for r in spec.rules] + [{"raw_points_total": sum(points)}],
        ml_details={"percentile": round(0.5 + spec.ml_score / 200, 3), "top_features": ["amount_z_user", "hour_sin"]} if spec.ml_score is not None else None,
        explanation=explanation,
        features_snapshot={"amount_rupees": spec.rupees, "hour_ist": spec.hour_ist, "is_new_beneficiary": "R1" in spec.rules},
        allowed_actions=ALLOWED_ACTIONS[level], assessed_at=analysed,
    )
    report.add("risk_assessments", True)
    transactions_repo.transition(txn, S.ANALYSED, at=analysed)
    transactions_repo.transition(txn, S.AWAITING_USER_ACTION, at=analysed, expires_at=initiated + timedelta(minutes=10))
    audit("TRANSACTION_ASSESSED", {"status": "INITIATED"},
          {"status": "AWAITING_USER_ACTION", "final_risk_score": final, "risk_level": str(level)}, analysed)

    if level != RiskLevel.LOW:
        alerts_repo.create(
            user_id=txn.user_id, transaction_id=txn.id, risk_assessment_id=assessment.id, alert_type=AlertType.RISK_WARNING,
            severity=AlertSeverity.CRITICAL if level == RiskLevel.HIGH else AlertSeverity.WARNING,
            title=f"{'High' if level == RiskLevel.HIGH else 'Medium'}-risk payment of Rs {spec.rupees:,}",
            message="; ".join(item["label"] for item in explanation) or "Review this payment before continuing.",
            created_at=analysed,
        )
        report.add("alerts", True)

    decided = initiated + timedelta(seconds=40)
    if spec.outcome == S.APPROVED:
        transactions_repo.transition(txn, S.APPROVED, at=decided, approval_method=spec.approval)
        audit("TRANSACTION_APPROVED", {"status": "AWAITING_USER_ACTION"}, {"status": "APPROVED", "approval_method": str(spec.approval)}, decided)
    elif spec.outcome == S.CANCELLED:
        transactions_repo.transition(txn, S.CANCELLED, at=decided)
        audit("TRANSACTION_CANCELLED", {"status": "AWAITING_USER_ACTION"}, {"status": "CANCELLED"}, decided)
        alerts_repo.create(user_id=txn.user_id, transaction_id=txn.id, alert_type=AlertType.TRANSACTION_CANCELLED,
                           severity=AlertSeverity.INFO, title="Payment cancelled",
                           message=f"Your payment of Rs {spec.rupees:,} was cancelled. Nothing was paid.", created_at=decided)
        report.add("alerts", True)
    elif spec.outcome == S.EXPIRED:
        expired = initiated + timedelta(minutes=10, seconds=5)
        transactions_repo.transition(txn, S.EXPIRED, at=expired)
        audit("TRANSACTION_EXPIRED", {"status": "AWAITING_USER_ACTION"}, {"status": "EXPIRED"}, expired)
        alerts_repo.create(user_id=txn.user_id, transaction_id=txn.id, alert_type=AlertType.TRANSACTION_EXPIRED,
                           severity=AlertSeverity.INFO, title="Payment expired",
                           message="No action was taken within 10 minutes, so the payment was not sent.", created_at=expired)
        report.add("alerts", True)


def run(settings: Settings) -> SeedReport:
    """CLI entry: checks preconditions, seeds in one transaction, commits."""
    if settings.is_production:
        raise SeedRefused("Refusing to seed: APP_ENV=production. Seed data is for development only.")
    database = Database(settings)
    if not database.is_configured:
        raise SeedRefused("DATABASE_URL is not set. Add it to backend/.env first.")
    try:
        with database.engine.connect() as connection:
            if not is_up_to_date(connection):
                raise SeedRefused(f"Database schema is not at the latest migration ({head_revision()}). "
                                  "Run: alembic upgrade head")
        session = database.create_session()
        try:
            report = seed_development_data(session, settings)
            session.commit()
            return report
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    finally:
        database.dispose()


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Load SakshamPay development seed data (never in production).").parse_args(argv)
    settings = get_settings()
    try:
        report = run(settings)
    except SeedRefused as exc:
        print(f"Seed refused: {exc}", file=sys.stderr)
        return 2
    print(f"Seed {SEED_VERSION} complete for database {settings.database_url_masked}")
    for kind in ("users", "beneficiaries", "transactions"):
        print(f"  {kind:<17} created {report.created.get(kind, 0):>3}   already present {report.existing.get(kind, 0):>3}")
    for kind in ("risk_assessments", "alerts", "audit_logs"):
        print(f"  {kind:<17} created {report.created.get(kind, 0):>3}   (skipped with their existing transactions)")
    print("Demo login (available once P-6 adds sign-in): any seed email, password SakshamDemo@2026")
    return 0


if __name__ == "__main__":
    sys.exit(main())
