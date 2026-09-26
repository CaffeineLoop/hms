"""HTTP middleware (Stage 6): request context, security headers, generic API auditing.

Generic auditing (one row per request, written after the response is produced):
- every non-GET /api request (writes, state changes), success or failure;
- GET requests that read patient or clinical data (routes with a patient or clinical
  resource) and reads of the audit trail itself;
- every 401/403 on any /api route (authentication/authorization failures).
Routes whose successes are audited explicitly by their service with richer metadata
(authentication, users, roles, permissions) are skipped here unless they fail.
Query strings and bodies are never recorded (they may contain patient data or secrets).
"""

import uuid

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from app.core.audit import AuditRecorder, RequestContext, request_context
from app.models.audit import AuditOutcome

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}

# First path segment after /api whose GETs expose patient/clinical data.
SENSITIVE_READ_SEGMENTS = {
    "patients", "encounters", "observations", "conditions", "allergies", "clinical-notes",
    "lab-orders", "lab-samples", "lab-results", "reports", "prescriptions", "appointments",
    "admissions", "audit-events",
}
# Successful calls to these are recorded by their services (explicit, richer events).
EXPLICITLY_AUDITED_PREFIXES = ("/api/auth/", "/api/users", "/api/roles")


def _resource(route: str | None, path_params: dict, location: str | None) -> tuple[str | None, str | None]:
    if location and location.startswith("/api/"):
        parts = location.strip("/").split("/")
        if len(parts) >= 3:
            return parts[1], parts[2]
    if not route:
        return None, None
    segments = route.strip("/").split("/")[1:]  # drop "api"
    for index in range(len(segments) - 1, 0, -1):
        if segments[index].startswith("{"):
            return segments[index - 1], path_params.get(segments[index][1:-1])
    return (segments[0] if segments else None), None


def _patient_id(path_params: dict, resource_type: str | None, resource_id: str | None) -> uuid.UUID | None:
    candidate = path_params.get("patient_id") or (resource_id if resource_type == "patients" else None)
    try:
        return uuid.UUID(str(candidate)) if candidate else None
    except ValueError:
        return None


def _should_audit(method: str, path: str, route: str | None, status: int) -> bool:
    if not path.startswith("/api/"):
        return False
    if route == "/api/auth/login":  # always audited by AuthService (success, failure, lockout)
        return False
    if status in (401, 403):
        return True
    if route is None:  # unmatched paths (404/405 noise) are not audited
        return False
    if status < 400 and route.startswith(EXPLICITLY_AUDITED_PREFIXES) and method != "GET":
        return False
    if method != "GET":
        return True
    segments = route.strip("/").split("/")
    return len(segments) > 1 and segments[1] in SENSITIVE_READ_SEGMENTS


def install_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def audit_and_harden(request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id")
        if not request_id or len(request_id) > 64 or not request_id.replace("-", "").isalnum():
            request_id = uuid.uuid4().hex
        context = RequestContext(
            request_id=request_id,
            client_ip=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        )
        token = request_context.set(context)
        try:
            response = await call_next(request)
            route_obj = request.scope.get("route")
            route = getattr(route_obj, "path", None)
            status = response.status_code
            if _should_audit(request.method, request.url.path, route, status):
                path_params = {k: str(v) for k, v in (request.scope.get("path_params") or {}).items()}
                resource_type, resource_id = _resource(route, path_params, response.headers.get("location"))
                outcome = (AuditOutcome.DENIED if status in (401, 403)
                           else AuditOutcome.SUCCESS if status < 400 else AuditOutcome.FAILURE)
                await run_in_threadpool(
                    AuditRecorder(request.app.state.engine).record,
                    f"{request.method} {route or 'unmatched'}",
                    outcome,
                    principal=getattr(request.state, "principal", None) or context.principal,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    patient_id=_patient_id(path_params, resource_type, resource_id),
                    http_method=request.method,
                    route=route or request.url.path[:200],
                    status_code=status,
                )
        finally:
            request_context.reset(token)
        response.headers["X-Request-ID"] = request_id
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if request.url.path.startswith("/api/"):
            # Patient data and tokens must never be stored by browsers or shared caches.
            response.headers["Cache-Control"] = "no-store"
        return response
