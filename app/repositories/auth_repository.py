"""Data access for users, roles, permissions and sessions (Stage 5). No rules, no commits."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select, update

from app.models.auth import AuthSession, Permission, Role, RolePermission, User, UserRole
from app.models.staff import RecordStatus, Staff
from app.repositories.staff_repository import BaseRepository, contains_pattern


class UserRepository(BaseRepository):
    model = User

    def by_username(self, username: str) -> User | None:
        return self._session.execute(select(User).where(User.username == username)).scalar_one_or_none()

    def by_staff_id(self, staff_id: uuid.UUID) -> User | None:
        return self._session.execute(select(User).where(User.staff_id == staff_id)).scalar_one_or_none()

    def search(self, *, filters: dict[str, Any], q: str | None, limit: int, offset: int):
        statement = self._filtered(filters)
        if q:
            statement = statement.where(User.username.ilike(contains_pattern(q), escape="\\"))
        return self._page(statement, (User.username,), limit, offset)

    def roles(self, user_id: uuid.UUID) -> list[Role]:
        statement = (
            select(Role).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id).order_by(Role.name)
        )
        return list(self._session.execute(statement).scalars())

    def effective_grants(self, user_id: uuid.UUID) -> tuple[bool, list[tuple[str, str]], set[uuid.UUID]]:
        """(is_superuser, [(permission code, scope)], active role ids) through ACTIVE roles only."""
        roles = [r for r in self.roles(user_id) if r.status == RecordStatus.ACTIVE]
        role_ids = {r.id for r in roles}
        grants: list[tuple[str, str]] = []
        if role_ids:
            grants = [
                (row.code, row.scope)
                for row in self._session.execute(
                    select(Permission.code, RolePermission.scope)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .where(RolePermission.role_id.in_(role_ids))
                )
            ]
        return any(r.is_superuser for r in roles), grants, role_ids

    def count_active_superusers(self) -> int:
        """Active users with active staff holding an active superuser role."""
        statement = (
            select(func.count(func.distinct(User.id)))
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .join(Staff, Staff.id == User.staff_id)
            .where(
                User.status == RecordStatus.ACTIVE,
                Staff.status == RecordStatus.ACTIVE,
                Role.status == RecordStatus.ACTIVE,
                Role.is_superuser.is_(True),
            )
        )
        return self._session.execute(statement).scalar_one()

    def get_assignment(self, user_id: uuid.UUID, role_id: uuid.UUID) -> UserRole | None:
        return self._session.get(UserRole, (user_id, role_id))

    def add_assignment(self, assignment: UserRole) -> None:
        self._session.add(assignment)
        self._session.flush()

    def delete_assignment(self, assignment: UserRole) -> None:
        self._session.delete(assignment)
        self._session.flush()


class RoleRepository(BaseRepository):
    model = Role

    def by_name(self, name: str) -> Role | None:
        return self._session.execute(select(Role).where(Role.name == name)).scalar_one_or_none()

    def search(self, *, status, limit: int, offset: int):
        return self._page(self._filtered({"status": status}), (Role.name,), limit, offset)

    def grants(self, role_id: uuid.UUID) -> list[tuple[Permission, str]]:
        statement = (
            select(Permission, RolePermission.scope)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
            .order_by(Permission.code)
        )
        return [(row[0], row[1]) for row in self._session.execute(statement)]

    def get_grant(self, role_id: uuid.UUID, permission_id: uuid.UUID) -> RolePermission | None:
        return self._session.get(RolePermission, (role_id, permission_id))

    def add_grant(self, grant: RolePermission) -> None:
        self._session.add(grant)
        self._session.flush()

    def delete_grant(self, grant: RolePermission) -> None:
        self._session.delete(grant)
        self._session.flush()

    def user_count(self, role_id: uuid.UUID) -> int:
        return self._session.execute(select(func.count()).select_from(UserRole).where(UserRole.role_id == role_id)).scalar_one()


class PermissionRepository(BaseRepository):
    model = Permission

    def all(self) -> list[Permission]:
        return list(self._session.execute(select(Permission).order_by(Permission.code)).scalars())

    def by_code(self, code: str) -> Permission | None:
        return self._session.execute(select(Permission).where(Permission.code == code)).scalar_one_or_none()


class SessionRepository(BaseRepository):
    model = AuthSession

    def active_by_digest(self, digest: str, now: datetime) -> tuple[AuthSession, User, Staff] | None:
        statement = (
            select(AuthSession, User, Staff)
            .join(User, User.id == AuthSession.user_id)
            .join(Staff, Staff.id == User.staff_id)
            .where(AuthSession.token_hash == digest, AuthSession.revoked_at.is_(None), AuthSession.expires_at > now)
        )
        row = self._session.execute(statement).one_or_none()
        return None if row is None else (row[0], row[1], row[2])

    def revoke_for_user(self, user_id: uuid.UUID, now: datetime, reason: str, *,
                        except_session_id: uuid.UUID | None = None) -> int:
        conditions = [AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)]
        if except_session_id is not None:
            conditions.append(AuthSession.id != except_session_id)
        result = self._session.execute(
            update(AuthSession).where(and_(*conditions)).values(revoked_at=now, revocation_reason=reason)
        )
        return result.rowcount

