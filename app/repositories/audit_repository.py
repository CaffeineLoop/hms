"""Read access to the audit trail (Stage 6). There are intentionally no update/delete methods."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.models.audit import AuditEvent, AuditOutcome
from app.repositories.staff_repository import BaseRepository

LOGIN_ACTION = "auth.login"


class AuditRepository(BaseRepository):
    model = AuditEvent

    def search(self, *, filters: dict[str, Any], occurred_from: datetime | None, occurred_to: datetime | None,
               limit: int, offset: int):
        statement = self._filtered(filters)
        if occurred_from is not None:
            statement = statement.where(AuditEvent.occurred_at >= occurred_from)
        if occurred_to is not None:
            statement = statement.where(AuditEvent.occurred_at <= occurred_to)
        return self._page(statement, (AuditEvent.occurred_at.desc(), AuditEvent.id), limit, offset)

    def recent_login_failures_for_username(self, username: str, since: datetime) -> tuple[int, datetime | None]:
        """Failures for `username` after max(since, last successful login); returns (count, latest)."""
        last_success = (
            select(func.max(AuditEvent.occurred_at))
            .where(AuditEvent.action == LOGIN_ACTION, AuditEvent.outcome == AuditOutcome.SUCCESS.value,
                   AuditEvent.actor_username == username)
            .scalar_subquery()
        )
        row = self._session.execute(
            select(func.count(), func.max(AuditEvent.occurred_at)).where(
                AuditEvent.action == LOGIN_ACTION,
                AuditEvent.outcome == AuditOutcome.FAILURE.value,
                AuditEvent.actor_username == username,
                AuditEvent.occurred_at > since,
                AuditEvent.occurred_at > func.coalesce(last_success, since),
            )
        ).one()
        return row[0], row[1]

    def recent_login_failures_for_ip(self, client_ip: str, since: datetime) -> tuple[int, datetime | None]:
        row = self._session.execute(
            select(func.count(), func.max(AuditEvent.occurred_at)).where(
                AuditEvent.action == LOGIN_ACTION,
                AuditEvent.outcome == AuditOutcome.FAILURE.value,
                AuditEvent.client_ip == client_ip,
                AuditEvent.occurred_at > since,
            )
        ).one()
        return row[0], row[1]

    def for_user(self, user_id: uuid.UUID) -> list[AuditEvent]:
        return list(self._session.execute(
            select(AuditEvent).where(AuditEvent.actor_user_id == user_id).order_by(AuditEvent.occurred_at)
        ).scalars())
