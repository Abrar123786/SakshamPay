"""Request and response models for /api/v1/beneficiaries (P-10).

Simulated payees only. A raw UPI ID or account reference is accepted once, in
the create request, and is never stored or returned: responses carry the masked
form only.
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import UtcDateTime


def _plain_text(value: str) -> str:
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("Use plain text without control characters.")
    return value


class BeneficiaryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    beneficiary_name: str = Field(min_length=1, max_length=100)
    upi_id: str | None = Field(default=None, max_length=320, repr=False)
    account_reference: str | None = Field(default=None, max_length=40, repr=False)
    bank_name: str | None = Field(default=None, max_length=100)

    @field_validator("upi_id", "account_reference", "bank_name", mode="before")
    @classmethod
    def _empty_is_missing(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("beneficiary_name", "bank_name")
    @classmethod
    def _names_are_plain_text(cls, value):
        return _plain_text(value) if value is not None else value

    @model_validator(mode="after")
    def _one_identifier(self):
        if (self.upi_id is None) == (self.account_reference is None):
            raise ValueError("Give either a UPI ID or an account reference (one of them).")
        if self.bank_name is not None and self.account_reference is None:
            raise ValueError("A bank name is only used with an account reference.")
        return self


class BeneficiaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    beneficiary_name: str
    bank_name: str | None
    upi_id_masked: str | None
    account_reference_masked: str | None
    is_verified: bool
    created_at: UtcDateTime


class BeneficiaryList(BaseModel):
    items: list[BeneficiaryOut]
