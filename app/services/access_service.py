"""User accounts, dynamic roles and role permissions (Stage 5).

Anti-escalation rules (PermissionDeniedError -> 403):
- nobody can change their OWN account's roles, status or password through admin endpoints;
- nobody can change the permissions of a role they currently hold;
- nobody can grant a permission (or a broader scope) they do not hold themselves;
- nobody can assign a role containing permissions they do not hold; only superusers can
  assign the superuser role.
Safety rules (ConflictError -> 409):
- the SUPER_ADMIN system role cannot be renamed, deactivated or have grants edited;
- the last active superuser cannot be deactivated or lose the superuser role.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.audit import AuditRecorder
from app.core.clock import utc_now
from app.core.errors import BusinessValidationError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import SCOPE_RANK, Scope
from app.core.principal import Principal
from app.core.security import hash_password
from app.models.auth import RevocationReason, Role, RolePermission, User, UserRole
from app.models.audit import AuditOutcome
from app.models.staff import RecordStatus
from app.repositories.auth_repository import PermissionRepository, RoleRepository, SessionRepository, UserRepository
from app.repositories.staff_repository import StaffRepository
from app.schemas.auth import PermissionGrant, RoleCreate, RoleListParams, RoleRead, RoleUpdate, UserCreate, UserListParams


class AccessService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._roles = RoleRepository(session)
        self._permissions = PermissionRepository(session)
        self._sessions = SessionRepository(session)
        self._staff = StaffRepository(session)
        self._audit = AuditRecorder(session.get_bind())

    # --- users ----------------------------------------------------------------------------

    def list_users(self, params: UserListParams):
        users, total = self._users.search(
            filters={"status": params.status}, q=params.q, limit=params.limit, offset=params.offset
        )
        return [self._user_view(u) for u in users], total

    def get_user(self, user_id: uuid.UUID) -> dict:
        return self._user_view(self._get_user(user_id))

    def create_user(self, actor: Principal, data: UserCreate) -> dict:
        staff = self._staff.get(data.staff_id)
        if staff is None:
            raise BusinessValidationError(f"staff_id {data.staff_id} does not refer to a staff member", field="staff_id")
        if staff.status != RecordStatus.ACTIVE:
            raise ConflictError(f"Staff member {staff.employee_code} is inactive.")
        if self._users.by_staff_id(staff.id) is not None:
            raise ConflictError(f"Staff member {staff.employee_code} already has a user account.")
        if self._users.by_username(data.username) is not None:
            raise ConflictError(f"Username {data.username} is already taken.")
        roles = [self._assignable_role(actor, role_id) for role_id in dict.fromkeys(data.role_ids)]
        user = User(
            staff_id=staff.id,
            username=data.username,
            password_hash=hash_password(data.password),
            status=RecordStatus.ACTIVE.value,
            password_changed_at=utc_now(),
        )
        self._users.add(user)
        for role in roles:
            self._users.add_assignment(UserRole(user_id=user.id, role_id=role.id, assigned_by_user_id=actor.user_id))
        self._session.commit()
        self._event("user.create", actor, "users", user.id,
                    username=user.username, staff_id=staff.id, roles=[r.name for r in roles])
        return self.get_user(user.id)

    def deactivate_user(self, actor: Principal, user_id: uuid.UUID) -> dict:
        user = self._get_user(user_id, for_update=True)
        self._not_self(actor, user, "deactivate your own account")
        if user.status == RecordStatus.INACTIVE:
            raise ConflictError(f"User {user.username} is already INACTIVE.")
        self._keep_a_superuser(user_losing_superuser=user)
        now = utc_now()
        user.status = RecordStatus.INACTIVE.value
        user.deactivated_at = now
        revoked = self._sessions.revoke_for_user(user.id, now, RevocationReason.USER_DEACTIVATED)
        self._session.commit()
        self._event("user.deactivate", actor, "users", user.id, username=user.username, sessions_revoked=revoked)
        return self.get_user(user.id)

    def reactivate_user(self, actor: Principal, user_id: uuid.UUID) -> dict:
        user = self._get_user(user_id, for_update=True)
        self._not_self(actor, user, "reactivate your own account")
        if user.status == RecordStatus.ACTIVE:
            raise ConflictError(f"User {user.username} is already ACTIVE.")
        user.status = RecordStatus.ACTIVE.value
        user.deactivated_at = None
        self._session.commit()
        self._event("user.reactivate", actor, "users", user.id, username=user.username)
        return self.get_user(user.id)

    def reset_password(self, actor: Principal, user_id: uuid.UUID, new_password: str) -> dict:
        user = self._get_user(user_id, for_update=True)
        self._not_self(actor, user, "reset your own password here (use /api/auth/change-password)")
        if user.username in new_password.lower():
            raise BusinessValidationError("password cannot contain the username", field="new_password")
        now = utc_now()
        user.password_hash = hash_password(new_password)
        user.password_changed_at = now
        revoked = self._sessions.revoke_for_user(user.id, now, RevocationReason.PASSWORD_RESET)
        self._session.commit()
        self._event("user.password_reset", actor, "users", user.id, username=user.username, sessions_revoked=revoked)
        return self.get_user(user.id)

    def assign_role(self, actor: Principal, user_id: uuid.UUID, role_id: uuid.UUID) -> dict:
        user = self._get_user(user_id, for_update=True)
        self._not_self(actor, user, "change your own roles")
        role = self._assignable_role(actor, role_id)
        if self._users.get_assignment(user.id, role.id) is not None:
            raise ConflictError(f"User {user.username} already has role {role.name}.")
        self._users.add_assignment(UserRole(user_id=user.id, role_id=role.id, assigned_by_user_id=actor.user_id))
        self._session.commit()
        self._event("user.role_assign", actor, "users", user.id, username=user.username,
                    role_id=role.id, role=role.name)
        return self.get_user(user.id)

    def remove_role(self, actor: Principal, user_id: uuid.UUID, role_id: uuid.UUID) -> dict:
        user = self._get_user(user_id, for_update=True)
        self._not_self(actor, user, "change your own roles")
        assignment = self._users.get_assignment(user.id, role_id)
        if assignment is None:
            raise NotFoundError(f"User {user.username} does not have role {role_id}.")
        role = self._roles.get(role_id)
        if role.is_superuser:
            if not actor.is_superuser:
                raise PermissionDeniedError("Only a superuser can remove the superuser role.")
            self._keep_a_superuser(user_losing_superuser=user)
        self._users.delete_assignment(assignment)
        self._session.commit()
        self._event("user.role_remove", actor, "users", user.id, username=user.username,
                    role_id=role.id, role=role.name)
        return self.get_user(user.id)

    # --- roles ----------------------------------------------------------------------------

    def list_roles(self, params: RoleListParams):
        roles, total = self._roles.search(status=params.status, limit=params.limit, offset=params.offset)
        return [self._role_view(r) for r in roles], total

    def get_role(self, role_id: uuid.UUID) -> RoleRead:
        return self._role_view(self._get_role(role_id))

    def create_role(self, actor: Principal, data: RoleCreate) -> RoleRead:
        if self._roles.by_name(data.name) is not None:
            raise ConflictError(f"A role named {data.name} already exists.")
        grants = [self._grantable(actor, g) for g in data.permissions]
        role = Role(name=data.name, description=data.description, status=RecordStatus.ACTIVE.value, is_superuser=False)
        self._roles.add(role)
        for permission, scope in grants:
            self._roles.add_grant(RolePermission(role_id=role.id, permission_id=permission.id, scope=scope,
                                                 granted_by_user_id=actor.user_id))
        self._session.commit()
        self._event("role.create", actor, "roles", role.id, role=role.name,
                    permissions=[f"{p.code}:{scope}" for p, scope in grants])
        return self.get_role(role.id)

    def update_role(self, actor: Principal, role_id: uuid.UUID, data: RoleUpdate) -> RoleRead:
        role = self._get_role(role_id, for_update=True)
        changes = data.model_dump(exclude_unset=True)
        if "name" in changes and changes["name"] != role.name:
            self._not_system(role, "renamed")
            if self._roles.by_name(changes["name"]) is not None:
                raise ConflictError(f"A role named {changes['name']} already exists.")
        previous = {field: getattr(role, field) for field in changes}
        for field, value in changes.items():
            setattr(role, field, value)
        self._session.commit()
        self._event("role.update", actor, "roles", role.id, role=role.name,
                    changes={f: {"from": previous[f], "to": v} for f, v in changes.items()})
        return self.get_role(role.id)

    def set_role_status(self, actor: Principal, role_id: uuid.UUID, status: RecordStatus) -> RoleRead:
        role = self._get_role(role_id, for_update=True)
        self._not_system(role, "deactivated or reactivated")
        if role.id in actor.role_ids:
            raise PermissionDeniedError("You cannot change the status of a role you hold.")
        if role.status == status:
            raise ConflictError(f"Role {role.name} is already {status.value}.")
        role.status = status.value
        self._session.commit()
        action = "role.deactivate" if status == RecordStatus.INACTIVE else "role.reactivate"
        self._event(action, actor, "roles", role.id, role=role.name)
        return self.get_role(role.id)

    def grant_permission(self, actor: Principal, role_id: uuid.UUID, grant: PermissionGrant) -> RoleRead:
        role = self._editable_grants_role(actor, role_id)
        permission, scope = self._grantable(actor, grant)
        existing = self._roles.get_grant(role.id, permission.id)
        previous_scope = existing.scope if existing is not None else None
        if existing is not None:
            if existing.scope == scope:
                raise ConflictError(f"Role {role.name} already has {permission.code} ({scope}).")
            existing.scope = scope  # change of scope
            existing.granted_by_user_id = actor.user_id
        else:
            self._roles.add_grant(RolePermission(role_id=role.id, permission_id=permission.id, scope=scope,
                                                 granted_by_user_id=actor.user_id))
        self._session.commit()
        self._event("role.permission_grant", actor, "roles", role.id, role=role.name, permission=permission.code,
                    scope=scope, previous_scope=previous_scope)
        return self.get_role(role.id)

    def revoke_permission(self, actor: Principal, role_id: uuid.UUID, code: str) -> RoleRead:
        role = self._editable_grants_role(actor, role_id)
        permission = self._permissions.by_code(code)
        grant = self._roles.get_grant(role.id, permission.id) if permission else None
        if grant is None:
            raise NotFoundError(f"Role {role.name} does not have permission {code}.")
        self._roles.delete_grant(grant)
        self._session.commit()
        self._event("role.permission_revoke", actor, "roles", role.id, role=role.name, permission=permission.code)
        return self.get_role(role.id)

    def list_permissions(self):
        return self._permissions.all()

    # --- audit ----------------------------------------------------------------------------

    def _event(self, action: str, actor: Principal, resource_type: str, resource_id, **details) -> None:
        self._audit.record(action, AuditOutcome.SUCCESS, principal=actor,
                           resource_type=resource_type, resource_id=resource_id, details=details)

    # --- rules ----------------------------------------------------------------------------

    @staticmethod
    def _not_self(actor: Principal, user: User, action: str) -> None:
        if actor.user_id == user.id:
            raise PermissionDeniedError(f"You cannot {action}.")

    @staticmethod
    def _not_system(role: Role, action: str) -> None:
        if role.is_superuser:
            raise ConflictError(f"The {role.name} system role cannot be {action}.")

    def _editable_grants_role(self, actor: Principal, role_id: uuid.UUID) -> Role:
        role = self._get_role(role_id, for_update=True)
        if role.is_superuser:
            raise ConflictError(f"The {role.name} system role implicitly holds every permission; it cannot be edited.")
        if role.id in actor.role_ids:
            raise PermissionDeniedError("You cannot change the permissions of a role you hold.")
        return role

    def _grantable(self, actor: Principal, grant: PermissionGrant):
        permission = self._permissions.by_code(grant.code)
        if permission is None:
            raise BusinessValidationError(f"unknown permission {grant.code}", field="code")
        held = actor.scope(permission.code)
        if held is None or SCOPE_RANK[held] < SCOPE_RANK[grant.scope]:
            raise PermissionDeniedError(f"You cannot grant {permission.code} ({grant.scope}) because you do not hold it.")
        return permission, grant.scope.value

    def _assignable_role(self, actor: Principal, role_id: uuid.UUID) -> Role:
        role = self._roles.get(role_id)
        if role is None:
            raise BusinessValidationError(f"role {role_id} does not exist", field="role_id")
        if role.status != RecordStatus.ACTIVE:
            raise ConflictError(f"Role {role.name} is inactive.")
        if role.is_superuser and not actor.is_superuser:
            raise PermissionDeniedError("Only a superuser can assign the superuser role.")
        for permission, scope in self._roles.grants(role.id):
            held = actor.scope(permission.code)
            if held is None or SCOPE_RANK[held] < SCOPE_RANK[Scope(scope)]:
                raise PermissionDeniedError(
                    f"You cannot assign role {role.name}: it includes {permission.code}, which you do not hold."
                )
        return role

    def _keep_a_superuser(self, *, user_losing_superuser: User) -> None:
        is_superuser, _, _ = self._users.effective_grants(user_losing_superuser.id)
        if is_superuser and user_losing_superuser.status == RecordStatus.ACTIVE and self._users.count_active_superusers() <= 1:
            raise ConflictError("This is the last active superuser; create another one first.")

    # --- views / lookups ------------------------------------------------------------------

    def _user_view(self, user: User) -> dict:
        view = {c: getattr(user, c) for c in (
            "id", "staff_id", "username", "status", "password_changed_at", "last_login_at", "deactivated_at",
            "created_at", "updated_at")}
        view["roles"] = self._users.roles(user.id)
        return view

    def _role_view(self, role: Role) -> RoleRead:
        return RoleRead(
            id=role.id, name=role.name, description=role.description, status=role.status,
            is_superuser=role.is_superuser,
            permissions=[{"code": p.code, "scope": s} for p, s in self._roles.grants(role.id)],
            user_count=self._roles.user_count(role.id),
            created_at=role.created_at, updated_at=role.updated_at,
        )

    def _get_user(self, user_id: uuid.UUID, *, for_update: bool = False) -> User:
        user = self._users.get(user_id, for_update=for_update)
        if user is None:
            raise NotFoundError(f"User {user_id} not found.")
        return user

    def _get_role(self, role_id: uuid.UUID, *, for_update: bool = False) -> Role:
        role = self._roles.get(role_id, for_update=for_update)
        if role is None:
            raise NotFoundError(f"Role {role_id} not found.")
        return role
