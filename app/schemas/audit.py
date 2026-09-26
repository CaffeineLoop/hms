"""API contract for reading the audit trail (Stage 6). There is no write contract."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.audit import AuditOutcome
from app.schemas.common import AnyClinicalTimestamp, PageParams


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    occurred_at: datetime
    request_id: str | None
    action: str
    outcome: AuditOutcome
    actor_user_id: uuid.UUID | None
    actor_username: str | None
    actor_staff_id: uuid.UUID | None
    session_id: uuid.UUID | None
    resource_type: str | None
    resource_id: str | None
    patient_id: uuid.UUID | None
    http_method: str | None
    route: str | None
    status_code: int | None
    client_ip: str | None
    user_agent: str | None
    details: dict[str, Any]


class AuditSearchParams(PageParams):
    action: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=200)] = None
    outcome: AuditOutcome | None = None
    actor_user_id: uuid.UUID | None = None
    resource_type: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=50)] = None
    resource_id: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=100)] = None
    patient_id: uuid.UUID | None = Field(default=None, description="Who accessed/changed this patient's records")
    occurred_from: AnyClinicalTimestamp | None = None
    occurred_to: AnyClinicalTimestamp | None = None

    @model_validator(mode="after")
    def _range(self) -> "AuditSearchParams":
        if self.occurred_from and self.occurred_to and self.occurred_to < self.occurred_from:
            raise ValueError("occurred_to cannot be before occurred_from")
        return self
