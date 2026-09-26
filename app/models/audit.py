"""Audit trail (Stage 6).

`audit_events` is append-only: a database trigger rejects UPDATE, DELETE and TRUNCATE, and
the API exposes read-only endpoints (permission `audit.view`). There are deliberately no
foreign keys: audit history must outlive (and never block changes to) the records it
describes, so actor/resource ids are stored as plain values plus name snapshots.

Metadata never contains secrets (passwords, tokens) or patient demographics; see
app/core/audit.py for the sanitizer.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.clinical_base import in_list


class AuditOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"  # the action was attempted and failed (e.g. wrong password, validation)
    DENIED = "DENIED"  # refused for security reasons (401/403, lockout)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    request_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(200))
    outcome: Mapped[str] = mapped_column(String(10))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column()
    actor_username: Mapped[str | None] = mapped_column(String(100))
    actor_staff_id: Mapped[uuid.UUID | None] = mapped_column()
    session_id: Mapped[uuid.UUID | None] = mapped_column()
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    patient_id: Mapped[uuid.UUID | None] = mapped_column()
    http_method: Mapped[str | None] = mapped_column(String(10))
    route: Mapped[str | None] = mapped_column(String(200))
    status_code: Mapped[int | None] = mapped_column(Integer)
    client_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    __table_args__ = (
        CheckConstraint(in_list("outcome", AuditOutcome), name="outcome_valid"),
        CheckConstraint("length(btrim(action)) > 0", name="action_not_blank"),
        CheckConstraint("jsonb_typeof(details) = 'object'", name="details_is_object"),
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_actor_user_id_occurred_at", "actor_user_id", "occurred_at"),
        Index("ix_audit_events_patient_id_occurred_at", "patient_id", "occurred_at"),
        Index("ix_audit_events_resource", "resource_type", "resource_id"),
        # Login-abuse counting (per username and per client IP).
        Index("ix_audit_events_login_username", "action", "actor_username", "occurred_at"),
        Index("ix_audit_events_login_ip", "action", "client_ip", "occurred_at"),
    )
