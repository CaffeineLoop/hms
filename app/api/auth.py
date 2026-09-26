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
from app.core.permissions import P
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
