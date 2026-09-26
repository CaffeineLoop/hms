"""Authentication endpoints (Stage 5).

    POST /api/auth/login             public: username + password -> bearer token
    GET  /api/auth/me                authenticated: current user, roles, effective permissions
    POST /api/auth/logout            authenticated: revoke this token
    POST /api/auth/logout-all        authenticated: revoke all of this user's tokens
    POST /api/auth/change-password   authenticated: revokes the user's other tokens
"""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.auth import CurrentPrincipal
from app.db.session import get_db
from app.schemas.auth import ChangePasswordRequest, LoginRequest, MeRead, TokenResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/auth", tags=["authentication"])

_401 = {401: {"description": "Not authenticated / invalid credentials"}}


def _service(request: Request, session: Session = Depends(get_db)) -> AuthService:
    return AuthService(session, request.app.state.settings)


@router.post("/login", response_model=TokenResponse, responses=_401)
def login(data: LoginRequest, request: Request, response: Response, service: AuthService = Depends(_service)):
    token, auth_session, user = service.login(data.username, data.password, request.headers.get("user-agent"))
    response.headers["Cache-Control"] = "no-store"
    principal = service.principal_for_token(token)
    return TokenResponse(access_token=token, expires_at=auth_session.expires_at, user=service.me(principal))


@router.get("/me", response_model=MeRead, responses=_401)
def me(principal: CurrentPrincipal, service: AuthService = Depends(_service)):
    return service.me(principal)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, responses=_401)
def logout(principal: CurrentPrincipal, service: AuthService = Depends(_service)) -> Response:
    service.logout(principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT, responses=_401)
def logout_all(principal: CurrentPrincipal, service: AuthService = Depends(_service)) -> Response:
    service.logout_everywhere(principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT, responses=_401)
def change_password(data: ChangePasswordRequest, principal: CurrentPrincipal,
                    service: AuthService = Depends(_service)) -> Response:
    service.change_password(principal, data.current_password, data.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
