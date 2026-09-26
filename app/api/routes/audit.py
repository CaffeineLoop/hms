"""Audit trail endpoints (Stage 6): read-only, permission `audit.view`.

    GET /api/audit-events          search (newest first)
    GET /api/audit-events/{id}     one event

There are no create/update/delete endpoints (405), and the table itself rejects
UPDATE/DELETE/TRUNCATE. Reading the audit trail is itself audited by the middleware.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.auth import requires
from app.core.errors import NotFoundError
from app.core.permissions import P
from app.db.session import get_db
from app.repositories.audit_repository import AuditRepository
from app.schemas.audit import AuditEventRead, AuditSearchParams
from app.schemas.common import Page

router = APIRouter(prefix="/api/audit-events", tags=["audit"])

_ERRORS = {401: {"description": "Not authenticated"}, 403: {"description": "Missing audit.view"}}


def _repository(session: Session = Depends(get_db)) -> AuditRepository:
    return AuditRepository(session)


Audit = Annotated[AuditRepository, Depends(_repository)]


@router.get("", response_model=Page[AuditEventRead], responses=_ERRORS, dependencies=[requires(P.AUDIT_VIEW)])
def search_audit_events(params: Annotated[AuditSearchParams, Query()], audit: Audit):
    filters = params.model_dump(exclude={"limit", "offset", "occurred_from", "occurred_to"})
    items, total = audit.search(filters=filters, occurred_from=params.occurred_from, occurred_to=params.occurred_to,
                                limit=params.limit, offset=params.offset)
    return {"items": [AuditEventRead.model_validate(i) for i in items], "total": total,
            "limit": params.limit, "offset": params.offset}


@router.get("/{event_id}", response_model=AuditEventRead, responses={**_ERRORS, 404: {"description": "Not found"}},
            dependencies=[requires(P.AUDIT_VIEW)])
def get_audit_event(event_id: uuid.UUID, audit: Audit):
    event = audit.get(event_id)
    if event is None:
        raise NotFoundError(f"Audit event {event_id} not found.")
    return event
