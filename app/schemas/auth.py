"""API contracts for authentication, users, roles and permissions (Stage 5).

Password policy is checked on every password that is SET (create/reset/change), never on
login (a policy change must not lock existing users out of logging in to change it).
"""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.permissions import Scope
from app.core.security import MAX_PASSWORD_LENGTH, check_password_policy
from app.models.staff import Designation, RecordStatus
from app.schemas.common import PageParams, optional_text


def _lower(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


def _upper(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


def _policy(value: str) -> str:
    check_password_policy(value)
    return value


Username = Annotated[str, BeforeValidator(_lower), StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{2,49}$")]
LoginUsername = Annotated[str, BeforeValidator(_lower), StringConstraints(min_length=1, max_length=50)]
# Passwords are never stripped or normalized: every character counts.
AnyPassword = Annotated[str, StringConstraints(min_length=1, max_length=MAX_PASSWORD_LENGTH)]
NewPassword = Annotated[str, StringConstraints(max_length=MAX_PASSWORD_LENGTH), AfterValidator(_policy)]
RoleName = Annotated[str, BeforeValidator(_upper), StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,49}$")]
PermissionCode = Annotated[str, BeforeValidator(_lower), StringConstraints(pattern=r"^[a-z][a-z_]*\.[a-z][a-z_]*$")]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- authentication -----------------------------------------------------------------------


class LoginRequest(_Input):
    username: LoginUsername
    password: AnyPassword


class ChangePasswordRequest(_Input):
    current_password: AnyPassword
    new_password: NewPassword

    @model_validator(mode="after")
    def _different(self) -> "ChangePasswordRequest":
        if self.new_password == self.current_password:
            raise ValueError("new_password must differ from current_password")
        return self


class GrantRead(BaseModel):
    code: str
    scope: Scope


class StaffSummary(_Output):
    id: uuid.UUID
    employee_code: str
    full_name: str
    designation: Designation
    department_id: uuid.UUID


class MeRead(BaseModel):
    user_id: uuid.UUID
    username: str
    staff: StaffSummary
    roles: list[str]
    is_superuser: bool
    permissions: list[GrantRead] = Field(description="Effective permissions through ACTIVE roles")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: MeRead


# --- users ----------------------------------------------------------------------------------


class UserCreate(_Input):
    staff_id: uuid.UUID
    username: Username
    password: NewPassword = Field(description="Initial password; share it securely and ask the user to change it")
    role_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _not_username(self) -> "UserCreate":
        check_password_policy(self.password, username=self.username)
        return self


class PasswordReset(_Input):
    new_password: NewPassword


class RoleAssign(_Input):
    role_id: uuid.UUID


class RoleSummary(_Output):
    id: uuid.UUID
    name: str
    status: RecordStatus
    is_superuser: bool


class UserRead(_Output):
    id: uuid.UUID
    staff_id: uuid.UUID
    username: str
    status: RecordStatus
    password_changed_at: datetime
    last_login_at: datetime | None
    deactivated_at: datetime | None
    roles: list[RoleSummary]
    created_at: datetime
    updated_at: datetime


class UserListParams(PageParams):
    status: RecordStatus | None = None
    q: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=50)] = None


# --- roles / permissions ---------------------------------------------------------------------


class PermissionGrant(_Input):
    code: PermissionCode
    scope: Scope = Scope.ALL


class RoleCreate(_Input):
    name: RoleName
    description: optional_text(500) = None
    permissions: list[PermissionGrant] = Field(default_factory=list, max_length=200)


class RoleUpdate(_Input):
    name: RoleName | None = None
    description: optional_text(500) = None

    @model_validator(mode="after")
    def _check(self) -> "RoleUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class RoleRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: RecordStatus
    is_superuser: bool
    permissions: list[GrantRead]
    user_count: int
    created_at: datetime
    updated_at: datetime


class RoleListParams(PageParams):
    status: RecordStatus | None = None


class PermissionRead(_Output):
    code: str
    description: str
