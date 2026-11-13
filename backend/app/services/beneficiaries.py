"""Beneficiary service (P-10): list and add simulated payees.

Identifiers are protected here, before they reach the repository: only a display
mask and a keyed fingerprint are stored (``app.utils.privacy``). The raw value is
not stored, logged or audited.
"""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import AuditActorType, Beneficiary, User
from app.repositories import AuditLogRepository, BeneficiaryRepository
from app.repositories.base import MAX_PAGE_SIZE
from app.schemas.beneficiaries import BeneficiaryCreate
from app.services.auth import ClientInfo
from app.utils.privacy import identifier_key, protect_account_reference, protect_upi_id


class BeneficiaryService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.beneficiaries = BeneficiaryRepository(session)
        self.audit = AuditLogRepository(session)

    def list(self, user: User) -> list[Beneficiary]:
        """The user's active payees, newest first."""
        return self.beneficiaries.list_for_user(user.id, limit=MAX_PAGE_SIZE)

    def add(self, user: User, request: BeneficiaryCreate, *, client: ClientInfo) -> Beneficiary:
        key = identifier_key(self.settings)
        upi = protect_upi_id(request.upi_id, key) if request.upi_id else None
        account = protect_account_reference(request.account_reference, key) if request.account_reference else None
        beneficiary = self.beneficiaries.create(
            user_id=user.id, beneficiary_name=request.beneficiary_name, bank_name=request.bank_name, upi=upi, account=account
        )
        self.audit.record(
            action="BENEFICIARY_ADDED",
            actor_type=AuditActorType.USER,
            user_id=user.id,
            entity_type="beneficiary",
            entity_id=beneficiary.id,
            metadata={"identifier_type": "upi" if upi else "account"},
            ip_address=client.ip_address,
            user_agent=client.user_agent,
        )
        self.session.commit()
        return beneficiary
