"""User, role and permission administration (Stage 5). All endpoints require permissions.

    /api/users                              GET (user.view), POST (user.manage)
    /api/users/{id}                         GET (user.view)
    /api/users/{id}/deactivate|reactivate   POST (user.manage)
    /api/users/{id}/reset-password          POST (user.manage)
    /api/users/{id}/roles                   POST (user.manage)            assign a role
    /api/users/{id}/roles/{role_id}         DELETE (user.manage)          remove a role
    /api/roles                              GET (role.manage | permission.manage), POST (role.manage)
    /api/roles/{id}                         GET (role.manage | permission.manage), PATCH (role.manage)
    /api/roles/{id}/deactivate|reactivate   POST (role.manage)
    /api/roles/{id}/permissions             POST (permission.manage)      grant (or change scope)
    /api/roles/{id}/permissions/{code}      DELETE (permission.manage)    revoke
    /api/permissions                        GET (role.manage | permission.manage)

The anti-escalation rules live in AccessService.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.auth import requires, requires_any
from app.core.permissions import P
from app.core.principal import Principal
from app.db.session import get_db
from app.models.staff import RecordStatus
from app.schemas.auth import (
    PasswordReset,
    PermissionGrant,
    PermissionRead,
    RoleAssign,
    RoleCreate,
    RoleListParams,
    RoleRead,
    RoleUpdate,
    UserCreate,
    UserListParams,
    UserRead,
)
from app.schemas.common import Page
from app.services.access_service import AccessService

router = APIRouter(prefix="/api")

_ERRORS = {
    401: {"description": "Not authenticated"},
    403: {"description": "Missing permission, or a self-escalation attempt"},
    404: {"description": "Not found"},
    409: {"description": "Conflict (duplicate, system role, last superuser, ...)"},
}


def _service(session: Session = Depends(get_db)) -> AccessService:
    return AccessService(session)


Access = Annotated[AccessService, Depends(_service)]
UserManager = Annotated[Principal, requires(P.USER_MANAGE)]
RoleManager = Annotated[Principal, requires(P.ROLE_MANAGE)]
PermissionManager = Annotated[Principal, requires(P.PERMISSION_MANAGE)]
ROLE_READERS = [requires_any(P.ROLE_MANAGE, P.PERMISSION_MANAGE)]


def _page(schema, result, params) -> dict:
    items, total = result
    return {"items": [schema.model_validate(i) for i in items], "total": total,
            "limit": params.limit, "offset": params.offset}


# --- users -------------------------------------------------------------------------------------

USERS = ["users"]


@router.get("/users", response_model=Page[UserRead], responses=_ERRORS, tags=USERS,
            dependencies=[requires(P.USER_VIEW)])
def list_users(params: Annotated[UserListParams, Query()], service: Access):
    return _page(UserRead, service.list_users(params), params)


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED, responses=_ERRORS, tags=USERS)
def create_user(data: UserCreate, response: Response, actor: UserManager, service: Access):
    user = service.create_user(actor, data)
    response.headers["Location"] = f"/api/users/{user['id']}"
    return user


@router.get("/users/{user_id}", response_model=UserRead, responses=_ERRORS, tags=USERS,
            dependencies=[requires(P.USER_VIEW)])
def get_user(user_id: uuid.UUID, service: Access):
    return service.get_user(user_id)


@router.post("/users/{user_id}/deactivate", response_model=UserRead, responses=_ERRORS, tags=USERS)
def deactivate_user(user_id: uuid.UUID, actor: UserManager, service: Access):
    return service.deactivate_user(actor, user_id)


@router.post("/users/{user_id}/reactivate", response_model=UserRead, responses=_ERRORS, tags=USERS)
def reactivate_user(user_id: uuid.UUID, actor: UserManager, service: Access):
    return service.reactivate_user(actor, user_id)


@router.post("/users/{user_id}/reset-password", response_model=UserRead, responses=_ERRORS, tags=USERS)
def reset_password(user_id: uuid.UUID, data: PasswordReset, actor: UserManager, service: Access):
    return service.reset_password(actor, user_id, data.new_password)


@router.post("/users/{user_id}/roles", response_model=UserRead, responses=_ERRORS, tags=USERS)
def assign_role(user_id: uuid.UUID, data: RoleAssign, actor: UserManager, service: Access):
    return service.assign_role(actor, user_id, data.role_id)


@router.delete("/users/{user_id}/roles/{role_id}", response_model=UserRead, responses=_ERRORS, tags=USERS)
def remove_role(user_id: uuid.UUID, role_id: uuid.UUID, actor: UserManager, service: Access):
    return service.remove_role(actor, user_id, role_id)


# --- roles / permissions --------------------------------------------------------------------------

ROLES = ["roles & permissions"]


@router.get("/roles", response_model=Page[RoleRead], responses=_ERRORS, tags=ROLES, dependencies=ROLE_READERS)
def list_roles(params: Annotated[RoleListParams, Query()], service: Access):
    return _page(RoleRead, service.list_roles(params), params)


@router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED, responses=_ERRORS, tags=ROLES)
def create_role(data: RoleCreate, response: Response, actor: RoleManager, service: Access):
    role = service.create_role(actor, data)
    response.headers["Location"] = f"/api/roles/{role.id}"
    return role


@router.get("/roles/{role_id}", response_model=RoleRead, responses=_ERRORS, tags=ROLES, dependencies=ROLE_READERS)
def get_role(role_id: uuid.UUID, service: Access):
    return service.get_role(role_id)


@router.patch("/roles/{role_id}", response_model=RoleRead, responses=_ERRORS, tags=ROLES)
def update_role(role_id: uuid.UUID, data: RoleUpdate, actor: RoleManager, service: Access):
    return service.update_role(actor, role_id, data)


@router.post("/roles/{role_id}/deactivate", response_model=RoleRead, responses=_ERRORS, tags=ROLES)
def deactivate_role(role_id: uuid.UUID, actor: RoleManager, service: Access):
    return service.set_role_status(actor, role_id, RecordStatus.INACTIVE)


@router.post("/roles/{role_id}/reactivate", response_model=RoleRead, responses=_ERRORS, tags=ROLES)
def reactivate_role(role_id: uuid.UUID, actor: RoleManager, service: Access):
    return service.set_role_status(actor, role_id, RecordStatus.ACTIVE)


@router.post("/roles/{role_id}/permissions", response_model=RoleRead, responses=_ERRORS, tags=ROLES)
def grant_permission(role_id: uuid.UUID, data: PermissionGrant, actor: PermissionManager, service: Access):
    return service.grant_permission(actor, role_id, data)


@router.delete("/roles/{role_id}/permissions/{code}", response_model=RoleRead, responses=_ERRORS, tags=ROLES)
def revoke_permission(role_id: uuid.UUID, code: str, actor: PermissionManager, service: Access):
    return service.revoke_permission(actor, role_id, code)


@router.get("/permissions", response_model=list[PermissionRead], responses=_ERRORS, tags=ROLES,
            dependencies=ROLE_READERS)
def list_permissions(service: Access):
    return service.list_permissions()
