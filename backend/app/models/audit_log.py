import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Index, String
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.database.base import Base
from app.models.common import CreatedAtMixin, assert_no_sensitive_keys, enum_column, make_append_only
from app.models.enums import AuditActorType

if TYPE_CHECKING:
    from app.models.transaction import Transaction
    from app.models.user import User

USER_AGENT_MAX_LENGTH = 512


class AuditLog(CreatedAtMixin, Base):
    """Append-only record of security and transaction events.

    ``user_id`` is the account the event concerns (NULL for system-wide events);
    ``actor_type`` says who acted. JSON fields reject credential-like keys, and the
    ORM refuses UPDATE and DELETE. ``ip_address`` holds a truncated network
    (/24 for IPv4, /48 for IPv6), never a full address.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("action ~ '^[A-Z][A-Z0-9_]{2,63}$'", name="action_format"),
        CheckConstraint("entity_type ~ '^[a-z][a-z_]{1,31}$'", name="entity_type_format"),
        CheckConstraint("(entity_type IS NULL) = (entity_id IS NULL)", name="entity_pair"),
        CheckConstraint("actor_type <> 'USER' OR user_id IS NOT NULL", name="user_actor_has_user"),
        CheckConstraint("jsonb_typeof(old_values) = 'object'", name="old_values_object"),
        CheckConstraint("jsonb_typeof(new_values) = 'object'", name="new_values_object"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        Index("ix_audit_logs_user_id_created_at", "user_id", "created_at"),
        Index("ix_audit_logs_transaction_id_created_at", "transaction_id", "created_at"),
        Index("ix_audit_logs_action_created_at", "action", "created_at"),
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_entity_type_entity_id", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True, sort_order=-100)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="RESTRICT")
    )
    actor_type: Mapped[AuditActorType] = mapped_column(enum_column(AuditActorType, "actor_type", 16))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # none_as_null: Python None is stored as SQL NULL, not the JSON value null.
    old_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # "metadata" is reserved on declarative classes, so the attribute has another name.
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB(none_as_null=True))
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(USER_AGENT_MAX_LENGTH))
    request_id: Mapped[str | None] = mapped_column(String(64))

    user: Mapped["User | None"] = relationship()
    transaction: Mapped["Transaction | None"] = relationship()

    @validates("old_values", "new_values", "event_metadata")
    def _no_sensitive_keys(self, key: str, value: Any) -> Any:
        return assert_no_sensitive_keys(value, key)

    @validates("user_agent")
    def _truncate_user_agent(self, _key: str, value: str | None) -> str | None:
        return value[:USER_AGENT_MAX_LENGTH] if value else value

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action} actor={self.actor_type}>"


make_append_only(AuditLog)
