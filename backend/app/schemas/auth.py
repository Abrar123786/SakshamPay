"""Request and response models for /api/v1/auth.

* Requests forbid unknown fields, so a client cannot smuggle in ``id``,
  ``is_active`` or ``password_hash``.
* Passwords are ``SecretStr``: they never appear in ``repr()``, logs or the
  422 error details (which carry only field location, message and type).
* Responses expose only safe profile fields; there is no field for the hash.
"""

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

# Same shapes the database CHECK constraints enforce (users table).
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")

PASSWORD_MIN_LENGTH = 10  # P-1 decision
PASSWORD_MAX_LENGTH = 128  # bounds hashing work per request


def _normalise_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not EMAIL_PATTERN.fullmatch(value):
        raise ValueError("Enter a valid email address.")
    return value


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class RegisterRequest(_Request):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "full_name": "Asha Rao",
                "email": "asha.rao@example.com",
                "phone_number": "+919876543210",
                "password": "a-long-passphrase",
            }
        },
    )

    full_name: Annotated[str, Field(min_length=1, max_length=100)]
    email: Annotated[str, Field(min_length=3, max_length=254)]
    phone_number: Annotated[str | None, Field(default=None, max_length=20)] = None
    password: SecretStr

    @field_validator("full_name")
    @classmethod
    def _full_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Full name must not be blank.")
        return value

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return _normalise_email(value)

    @field_validator("phone_number")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = re.sub(r"[\s-]", "", value)
        if not value:
            return None
        if not PHONE_PATTERN.fullmatch(value):
            raise ValueError("Phone number must be in international format, e.g. +919876543210.")
        return value

    @field_validator("password")
    @classmethod
    def _password(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) < PASSWORD_MIN_LENGTH:
            raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")
        if len(raw) > PASSWORD_MAX_LENGTH:
            raise ValueError(f"Password must be at most {PASSWORD_MAX_LENGTH} characters.")
        if not raw.strip():
            raise ValueError("Password must not be only spaces.")
        return value

    @model_validator(mode="after")
    def _password_differs_from_email(self) -> "RegisterRequest":
        if self.password.get_secret_value().strip().lower() == self.email:
            raise ValueError("Password must not be the same as the email address.")
        return self


class LoginRequest(_Request):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"email": "asha.rao@example.com", "password": "a-long-passphrase"}},
    )

    email: Annotated[str, Field(min_length=3, max_length=254)]
    # Only bounded here: the registration rules are not repeated, so a login attempt
    # with a short password fails as "invalid credentials" like any other wrong password.
    password: SecretStr

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return _normalise_email(value)

    @field_validator("password")
    @classmethod
    def _password(cls, value: SecretStr) -> SecretStr:
        if not 1 <= len(value.get_secret_value()) <= PASSWORD_MAX_LENGTH:
            raise ValueError(f"Password must be 1-{PASSWORD_MAX_LENGTH} characters.")
        return value


class TokenResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 1800,
                "expires_at": "2026-11-09T10:30:00Z",
            }
        }
    )

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # seconds
    expires_at: datetime


class UserProfile(BaseModel):
    """Safe public view of a user: no hash, no lockout counters."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str
    phone_number: str | None
    is_active: bool
    created_at: datetime
