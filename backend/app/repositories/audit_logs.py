import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.logging import request_id_var
from app.models import AuditActorType, AuditLog
from app.repositories.base import Repository, clamp_limit, clamp_offset
from app.utils.privacy import truncate_ip_address


class AuditLogRepository(Repository):
    """Append-only audit trail: ``record`` and reads only.

    Protected three ways: no update/delete methods here, the ORM refuses changes
    (P-4), and database triggers refuse UPDATE/DELETE/TRUNCATE (P-5 migration).
    IP addresses are truncated before storage and the current request ID is
    attached automatically.
    """

    def record(
        self,
        *,
        action: str,
        actor_type: AuditActorType,
        user_id: uuid.UUID | None = None,
        transaction_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            action=action,
            actor_type=actor_type,
            user_id=user_id,
            transaction_id=transaction_id,
            entity_type=entity_type,
            entity_id=entity_id,
            old_values=old_values,
            new_values=new_values,
            event_metadata=metadata,
            ip_address=truncate_ip_address(ip_address),
            user_agent=user_agent,
            request_id=request_id or request_id_var.get(),
        )
        self.add(entry)
        return entry

    def find(
        self,
        *,
        user_id: uuid.UUID | None = None,
        transaction_id: uuid.UUID | None = None,
        action: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[AuditLog]:
        """Newest first, filtered by any combination of user, transaction, action and time."""
        query = select(AuditLog)
        if user_id is not None:
            query = query.where(AuditLog.user_id == user_id)
        if transaction_id is not None:
            query = query.where(AuditLog.transaction_id == transaction_id)
        if action is not None:
            query = query.where(AuditLog.action == action)
        if since is not None:
            query = query.where(AuditLog.created_at >= since)
        if until is not None:
            query = query.where(AuditLog.created_at < until)
        query = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        return list(self.session.scalars(query.limit(clamp_limit(limit)).offset(clamp_offset(offset))))

    def history_for_transaction(self, transaction_id: uuid.UUID) -> list[AuditLog]:
        """Every event for one transaction, oldest first (its full story)."""
        return list(
            self.session.scalars(
                select(AuditLog).where(AuditLog.transaction_id == transaction_id).order_by(AuditLog.id)
            )
        )

    def exists_with_request_id(self, request_id: str) -> bool:
        return self.session.scalar(select(AuditLog.id).where(AuditLog.request_id == request_id).limit(1)) is not None
