"""Reusable authentication/authorization dependencies (Stage 5).

Every protected route declares what it needs:

    @router.get("/things", dependencies=[requires(P.THING_VIEW)])
    def list_things(...): ...

or, when the handler also needs the caller (e.g. for scope):

    def act(principal: Annotated[Principal, requires(P.THING_MANAGE)]): ...

- no/invalid/expired/revoked token -> 401 (WWW-Authenticate: Bearer)
- valid token without the permission -> 403
Decisions use permission codes only; role names never appear in route code.
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.audit import request_context
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.permissions import P, Scope
from app.core.principal import Principal
from app.db.session import get_db
from app.services.auth_service import AuthService

bearer_scheme = HTTPBearer(auto_error=False, description="Session token from POST /api/auth/login")


def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db),
) -> Principal:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Not authenticated.")
    principal = AuthService(session, request.app.state.settings).principal_for_token(credentials.credentials)
    # Stage 6: make the caller available to auditing (middleware and services).
    request.state.principal = principal
    context = request_context.get()
    if context is not None:
        context.principal = principal
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def requires(*permissions: P):
    """Dependency: the caller must hold ALL of `permissions`."""

    def check(principal: CurrentPrincipal) -> Principal:
        missing = sorted(str(p) for p in permissions if not principal.has(p))
        if missing:
            raise PermissionDeniedError(f"Missing permission: {', '.join(missing)}.")
        return principal

    check.required_permissions = tuple(permissions)  # introspected by the route-coverage test
    return Depends(check)


def requires_any(*permissions: P):
    """Dependency: the caller must hold AT LEAST ONE of `permissions`."""

    def check(principal: CurrentPrincipal) -> Principal:
        if not any(principal.has(p) for p in permissions):
            raise PermissionDeniedError(f"Missing permission: one of {', '.join(sorted(map(str, permissions)))}.")
        return principal

    check.required_permissions = tuple(permissions)
    return Depends(check)


CLINICAL_SCOPE_DENIED = "You are not permitted to view patients' clinical records."


def requires_clinical_read(permission: P):
    """Dependency for reading patient clinical records: `permission` AND patient.view, both at ALL scope.

    OWN grants no record-level access to clinical records (see app/core/permissions.py), so an OWN-only grant
    is refused like the AI service does. Runs before the handler loads anything, so a denied caller learns
    nothing about the requested record - not even whether it exists.
    """

    def check(principal: CurrentPrincipal) -> Principal:
        needed = (permission, P.PATIENT_VIEW)
        missing = sorted(str(p) for p in needed if not principal.has(p))
        if missing:
            raise PermissionDeniedError(f"Missing permission: {', '.join(missing)}.")
        if any(principal.scope(p) != Scope.ALL for p in needed):
            raise PermissionDeniedError(CLINICAL_SCOPE_DENIED)
        return principal

    check.required_permissions = (permission, P.PATIENT_VIEW)
    return Depends(check)


CLINICAL_WRITE_SCOPE_DENIED = (
    "Your {permission} permission is limited to your own records (OWN scope); "
    "writing patient clinical records requires it for all patients (ALL scope)."
)


def requires_clinical_write(permission: P):
    """Dependency for writing patient clinical records: `permission` held at ALL scope.

    Clinical records have no owner notion, so OWN grants no record-level access (see app/core/permissions.py):
    an OWN-only grant is refused with 403, like the clinical-read rule. Runs before the handler touches anything.
    """

    def check(principal: CurrentPrincipal) -> Principal:
        if not principal.has(permission):
            raise PermissionDeniedError(f"Missing permission: {permission}.")
        if principal.scope(permission) != Scope.ALL:
            raise PermissionDeniedError(CLINICAL_WRITE_SCOPE_DENIED.format(permission=permission))
        return principal

    check.required_permissions = (permission,)
    return Depends(check)
