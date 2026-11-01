import uuid

from sqlalchemy import or_, select

from app.models import Beneficiary
from app.repositories.base import Repository, clamp_limit, clamp_offset
from app.repositories.errors import BeneficiaryNotFoundError, DuplicateBeneficiaryError
from app.utils.privacy import ProtectedIdentifier

_UNSET = object()


class BeneficiaryRepository(Repository):
    """Payees saved by a user. Every read is scoped to the owning user.

    Identifiers arrive already protected (``app.utils.privacy``): the repository
    never sees a full account number or UPI ID. Identifiers are immutable; a
    different account means a different beneficiary. Beneficiaries are deactivated,
    never deleted, so transaction history keeps pointing at them.
    """

    _translations = {
        "uq_beneficiaries_user_id_account_reference_fingerprint": DuplicateBeneficiaryError,
        "uq_beneficiaries_user_id_upi_id_fingerprint": DuplicateBeneficiaryError,
    }

    def create(
        self,
        *,
        user_id: uuid.UUID,
        beneficiary_name: str,
        bank_name: str | None = None,
        account: ProtectedIdentifier | None = None,
        upi: ProtectedIdentifier | None = None,
        is_verified: bool = False,
    ) -> Beneficiary:
        beneficiary = Beneficiary(
            user_id=user_id,
            beneficiary_name=beneficiary_name.strip(),
            bank_name=bank_name.strip() if bank_name else None,
            account_reference_masked=account.masked if account else None,
            account_reference_fingerprint=account.fingerprint if account else None,
            upi_id_masked=upi.masked if upi else None,
            upi_id_fingerprint=upi.fingerprint if upi else None,
            is_verified=is_verified,
        )
        self.add(beneficiary, self._translations)
        return beneficiary

    def get_for_user(
        self, beneficiary_id: uuid.UUID, user_id: uuid.UUID, *, include_inactive: bool = False
    ) -> Beneficiary | None:
        query = select(Beneficiary).where(Beneficiary.id == beneficiary_id, Beneficiary.user_id == user_id)
        if not include_inactive:
            query = query.where(Beneficiary.is_active.is_(True))
        return self.session.scalar(query)

    def require_for_user(self, beneficiary_id: uuid.UUID, user_id: uuid.UUID) -> Beneficiary:
        beneficiary = self.get_for_user(beneficiary_id, user_id)
        if beneficiary is None:
            raise BeneficiaryNotFoundError()
        return beneficiary

    def find_by_identifier(
        self, user_id: uuid.UUID, *, account: ProtectedIdentifier | None = None, upi: ProtectedIdentifier | None = None
    ) -> Beneficiary | None:
        """Existing payee (active or not) with the same account reference or UPI ID."""
        conditions = []
        if account:
            conditions.append(Beneficiary.account_reference_fingerprint == account.fingerprint)
        if upi:
            conditions.append(Beneficiary.upi_id_fingerprint == upi.fingerprint)
        if not conditions:
            return None
        return self.session.scalar(select(Beneficiary).where(Beneficiary.user_id == user_id, or_(*conditions)))

    def list_for_user(
        self, user_id: uuid.UUID, *, include_inactive: bool = False, limit: int | None = None, offset: int | None = None
    ) -> list[Beneficiary]:
        query = select(Beneficiary).where(Beneficiary.user_id == user_id)
        if not include_inactive:
            query = query.where(Beneficiary.is_active.is_(True))
        query = query.order_by(Beneficiary.created_at.desc(), Beneficiary.id).limit(clamp_limit(limit)).offset(
            clamp_offset(offset)
        )
        return list(self.session.scalars(query))

    def update(
        self, beneficiary: Beneficiary, *, beneficiary_name=_UNSET, bank_name=_UNSET, is_verified=_UNSET
    ) -> Beneficiary:
        if beneficiary_name is not _UNSET:
            beneficiary.beneficiary_name = beneficiary_name.strip()
        if bank_name is not _UNSET:
            beneficiary.bank_name = bank_name.strip() if bank_name else None
        if is_verified is not _UNSET:
            beneficiary.is_verified = bool(is_verified)
        self.flush()
        return beneficiary

    def deactivate(self, beneficiary: Beneficiary) -> Beneficiary:
        beneficiary.is_active = False
        self.flush()
        return beneficiary

    def reactivate(self, beneficiary: Beneficiary) -> Beneficiary:
        beneficiary.is_active = True
        self.flush()
        return beneficiary
