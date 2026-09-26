"""Authentication and dynamic RBAC (Stage 5).

    User ──< UserRole >── Role ──< RolePermission (+scope) >── Permission

- A User is the login account of exactly one Staff member (staff hold the clinical
  references from Stage 4; users only add credentials and roles).
- Roles and their permissions are data, managed through the API. The SUPER_ADMIN system
  role (`is_superuser`) implicitly holds every permission, including ones added later.
- Permission codes are fixed by the code catalog (app/core/permissions.py).
- AuthSession stores only SHA-256(token); logout/deactivation revokes sessions immediately.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.permissions import Scope
from app.db.base import Base
from app.models.clinical_base import in_list
from app.models.staff import RecordStatus


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _updated() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


def _user_fk() -> ForeignKey:
    return ForeignKey("users.id", ondelete="RESTRICT")


class RevocationReason(StrEnum):
    """Why a session stopped being valid before its expiry (Stage 6)."""

    LOGOUT = "LOGOUT"
    LOGOUT_ALL = "LOGOUT_ALL"
    PASSWORD_CHANGE = "PASSWORD_CHANGE"
    PASSWORD_RESET = "PASSWORD_RESET"
    USER_DEACTIVATED = "USER_DEACTIVATED"
    STAFF_DEACTIVATED = "STAFF_DEACTIVATED"
    IDLE_TIMEOUT = "IDLE_TIMEOUT"
    LEGACY = "LEGACY"  # revoked before Stage 6 recorded reasons


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _id()
    staff_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff.id", ondelete="RESTRICT"), unique=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(10))
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    __table_args__ = (
        CheckConstraint(r"username ~ '^[a-z0-9][a-z0-9._-]{2,49}$'", name="username_format"),
        CheckConstraint(in_list("status", RecordStatus), name="status_valid"),
        CheckConstraint("password_hash LIKE 'scrypt$%'", name="password_hash_format"),
        CheckConstraint("(status = 'INACTIVE') = (deactivated_at IS NOT NULL)", name="deactivation_matches_status"),
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10))
    is_superuser: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    __table_args__ = (
        CheckConstraint(r"name ~ '^[A-Z][A-Z0-9_]{1,49}$'", name="name_format"),
        CheckConstraint(in_list("status", RecordStatus), name="status_valid"),
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (CheckConstraint(r"code ~ '^[a-z][a-z_]*\.[a-z][a-z_]*$'", name="code_format"),)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("permissions.id", ondelete="RESTRICT"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(10), server_default=text("'ALL'"))
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    granted_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint(in_list("scope", Scope), name="scope_valid"),
        Index("ix_role_permissions_permission_id", "permission_id"),
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True)
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    assigned_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_user_roles_role_id", "role_id"),)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(30))  # Stage 6
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())  # Stage 6
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_format"),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        CheckConstraint(
            f"(revoked_at IS NULL) = (revocation_reason IS NULL) AND "
            f"(revocation_reason IS NULL OR {in_list('revocation_reason', RevocationReason)})",
            name="revocation_matches_reason",
        ),
        Index("ix_auth_sessions_user_id", "user_id"),
    )
