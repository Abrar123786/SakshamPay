"""Building blocks shared by the model modules (kept small on purpose)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, event, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

HEX64_PATTERN = "^[0-9a-f]{64}$"


def enum_column(enum_class: type[StrEnum], name: str, length: int) -> Enum:
    """VARCHAR(length) + CHECK constraint named ``ck_<table>_<name>``."""
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=length,
        validate_strings=True,
        values_callable=lambda members: [m.value for m in members],
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        sort_order=-100,  # list the key first in CREATE TABLE
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), sort_order=100
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), sort_order=101
    )


class ImmutableRecordError(RuntimeError):
    """Raised when code tries to change or delete an append-only record."""


def make_append_only(model: type) -> None:
    """Refuse UPDATE and DELETE of ``model`` rows through the ORM session."""

    def _refuse(operation: str):
        def listener(_mapper: Any, _connection: Any, target: Any) -> None:
            raise ImmutableRecordError(f"{type(target).__name__} records are append-only; {operation} is not allowed")

        return listener

    event.listen(model, "before_update", _refuse("update"))
    event.listen(model, "before_delete", _refuse("delete"))


# Keys that must never appear in audit or risk JSON (compared case-insensitively,
# after removing "-" and "_").
FORBIDDEN_JSON_KEYS = frozenset(
    {
        "password",
        "passwordhash",
        "newpassword",
        "currentpassword",
        "token",
        "accesstoken",
        "refreshtoken",
        "jwt",
        "secret",
        "jwtsecretkey",
        "apikey",
        "authorization",
        "otp",
    }
)


def assert_no_sensitive_keys(value: Any, field_name: str) -> Any:
    """Reject JSON containing credential-like keys at any depth."""

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                normalised = str(key).lower().replace("_", "").replace("-", "")
                if normalised in FORBIDDEN_JSON_KEYS:
                    raise ValueError(f"{field_name} must not contain sensitive key {key!r}")
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return value
