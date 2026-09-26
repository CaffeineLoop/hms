"""Audit recording (Stage 6).

- `request_context` holds per-request facts (request id, client IP, user agent, the
  authenticated principal) in a ContextVar set by the HTTP middleware, so services can
  record events without threading request objects through the layers.
- `AuditRecorder.record()` writes in its OWN short transaction on a separate connection:
  events about failed/denied actions survive the rollback of the business transaction,
  and audit rows are never part of work that is later rolled back.
- `sanitize()` guarantees metadata never carries secrets: keys that look like passwords,
  tokens or secrets are dropped, values are reduced to short scalars, and structure depth
  is capped. Callers only pass identifiers/codes (never patient demographics).
If writing an audit row fails the request is not failed; the error class is logged.
"""

import logging
import re
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, insert
from sqlalchemy.exc import SQLAlchemyError

from app.core.principal import Principal
from app.models.audit import AuditEvent, AuditOutcome

logger = logging.getLogger(__name__)

_SECRET_KEY = re.compile(r"pass(word|wd)?|secret|token|authorization|credential|cookie|api[_-]?key", re.I)
_MAX_STRING = 200
_MAX_ITEMS = 50


@dataclass
class RequestContext:
    request_id: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    principal: Principal | None = None
    extra: dict = field(default_factory=dict)


request_context: ContextVar[RequestContext | None] = ContextVar("hms_request_context", default=None)


def sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            str(k)[:64]: sanitize(v, depth + 1)
            for k, v in list(value.items())[:_MAX_ITEMS]
            if not _SECRET_KEY.search(str(k))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize(v, depth + 1) for v in list(value)[:_MAX_ITEMS]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:_MAX_STRING]


class AuditRecorder:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record(
        self,
        action: str,
        outcome: AuditOutcome,
        *,
        principal: Principal | None = None,
        actor_username: str | None = None,
        resource_type: str | None = None,
        resource_id: Any = None,
        patient_id: uuid.UUID | None = None,
        http_method: str | None = None,
        route: str | None = None,
        status_code: int | None = None,
        details: dict | None = None,
    ) -> None:
        ctx = request_context.get() or RequestContext()
        principal = principal or ctx.principal
        values = {
            "action": action[:200],
            "outcome": outcome.value,
            "request_id": ctx.request_id,
            "client_ip": ctx.client_ip,
            "user_agent": ctx.user_agent,
            "actor_user_id": principal.user_id if principal else None,
            "actor_username": (actor_username or (principal.username if principal else None) or None),
            "actor_staff_id": principal.staff_id if principal else None,
            "session_id": principal.session_id if principal else None,
            "resource_type": resource_type,
            "resource_id": str(resource_id)[:100] if resource_id is not None else None,
            "patient_id": patient_id,
            "http_method": http_method,
            "route": route,
            "status_code": status_code,
            "details": sanitize(details or {}),
        }
        if values["actor_username"]:
            values["actor_username"] = values["actor_username"][:100]
        try:
            with self._engine.begin() as connection:
                connection.execute(insert(AuditEvent).values(**values))
        except SQLAlchemyError as exc:  # never fail the request because auditing failed
            logger.error("Audit write failed for %s: %s", action, type(exc).__name__)
