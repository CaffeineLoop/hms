"""Authentication: login, bearer-token resolution, logout, password change (Stages 5-6).

- Login failures are indistinguishable (unknown user, wrong password, inactive user or
  inactive staff all return the same 401 message; unknown users still pay for a hash check).
- Stage 6 login abuse protection: failures are audited; once a username reaches
  LOGIN_MAX_FAILURES_PER_USER failures (since its last success, within the lockout window)
  or a client IP reaches LOGIN_MAX_FAILURES_PER_IP, further attempts get 429 with
  Retry-After, whether or not the username exists and even with the right password, until
  the window passes. The reason is recorded in the audit trail, never returned.
- A token is valid only while its session is unexpired, unrevoked and not idle for longer
  than AUTH_IDLE_TIMEOUT_MINUTES, AND the user and their staff record are ACTIVE.
- Every revocation records its reason (logout, password change, idle timeout, ...).
"""

import math
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.audit import AuditRecorder, request_context
from app.core.clock import utc_now
from app.core.config import Settings
from app.core.errors import AuthenticationError, BusinessValidationError, RateLimitedError
from app.core.permissions import SCOPE_RANK, Scope
from app.core.principal import Principal
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    check_password_policy,
    hash_password,
    needs_rehash,
    new_session_token,
    token_digest,
    verify_password,
)
from app.models.audit import AuditOutcome
from app.models.auth import AuthSession, RevocationReason, User
from app.models.staff import RecordStatus
from app.repositories.audit_repository import LOGIN_ACTION, AuditRepository
from app.repositories.auth_repository import SessionRepository, UserRepository
from app.repositories.staff_repository import StaffRepository
from app.schemas.auth import MeRead

INVALID_LOGIN = "Invalid username or password."
INVALID_TOKEN = "Invalid or expired token."
TOO_MANY_ATTEMPTS = "Too many failed login attempts. Try again later."
# last_seen_at is refreshed at most this often (avoids a write on every request).
LAST_SEEN_RESOLUTION = timedelta(seconds=60)


class AuthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._sessions = SessionRepository(session)
        self._staff = StaffRepository(session)
        self._audit_log = AuditRepository(session)
        self._audit = AuditRecorder(session.get_bind())

    # --- login -----------------------------------------------------------------------------

    def login(self, username: str, password: str, user_agent: str | None = None) -> tuple[str, AuthSession, User]:
        self._enforce_login_limits(username)
        user = self._users.by_username(username)
        if user is None:
            verify_password(password, DUMMY_PASSWORD_HASH)  # equalize timing
            self._login_failed(username, "unknown_user")
        if not verify_password(password, user.password_hash):
            self._login_failed(username, "bad_password", user=user)
        staff = self._staff.get(user.staff_id)
        if user.status != RecordStatus.ACTIVE or staff.status != RecordStatus.ACTIVE:
            self._login_failed(username, "inactive_account", user=user)
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        now = utc_now()
        token = new_session_token()
        auth_session = AuthSession(
            user_id=user.id,
            token_hash=token_digest(token),
            expires_at=now + timedelta(minutes=self._settings.auth_token_ttl_minutes),
            last_seen_at=now,
            user_agent=(user_agent or "")[:255] or None,
        )
        self._sessions.add(auth_session)
        user.last_login_at = now
        self._session.commit()
        self._audit.record(
            LOGIN_ACTION, AuditOutcome.SUCCESS,
            principal=Principal(user_id=user.id, staff_id=user.staff_id, username=user.username,
                                session_id=auth_session.id),
            resource_type="sessions", resource_id=auth_session.id,
            details={"expires_at": auth_session.expires_at.isoformat()},
        )
        return token, auth_session, user

    def _enforce_login_limits(self, username: str) -> None:
        window = timedelta(minutes=self._settings.login_lockout_minutes)
        since = utc_now() - window
        checks = [("username", *self._audit_log.recent_login_failures_for_username(username, since),
                   self._settings.login_max_failures_per_user)]
        client_ip = getattr(request_context.get(), "client_ip", None)
        if client_ip:
            checks.append(("client_ip", *self._audit_log.recent_login_failures_for_ip(client_ip, since),
                           self._settings.login_max_failures_per_ip))
        for scope, count, latest, limit in checks:
            if count >= limit:
                retry_after = max(1, math.ceil(((latest + window) - utc_now()).total_seconds()))
                self._audit.record(LOGIN_ACTION, AuditOutcome.DENIED, actor_username=username,
                                   details={"reason": "locked", "limit_scope": scope, "failures": count})
                raise RateLimitedError(TOO_MANY_ATTEMPTS, retry_after)

    def _login_failed(self, username: str, reason: str, user: User | None = None):
        self._session.rollback()
        principal = (Principal(user_id=user.id, staff_id=user.staff_id, username=user.username) if user else None)
        self._audit.record(LOGIN_ACTION, AuditOutcome.FAILURE, principal=principal, actor_username=username,
                           details={"reason": reason})
        raise AuthenticationError(INVALID_LOGIN)

    # --- token resolution ------------------------------------------------------------------

    def principal_for_token(self, token: str) -> Principal:
        now = utc_now()
        found = self._sessions.active_by_digest(token_digest(token), now)
        if found is None:
            raise AuthenticationError(INVALID_TOKEN)
        auth_session, user, staff = found
        if user.status != RecordStatus.ACTIVE or staff.status != RecordStatus.ACTIVE:
            raise AuthenticationError(INVALID_TOKEN)
        if self._idle_expired(auth_session, now):
            auth_session.revoked_at = now
            auth_session.revocation_reason = RevocationReason.IDLE_TIMEOUT.value
            self._session.commit()
            self._audit.record(
                "auth.session_revoked", AuditOutcome.SUCCESS,
                principal=Principal(user_id=user.id, staff_id=user.staff_id, username=user.username,
                                    session_id=auth_session.id),
                resource_type="sessions", resource_id=auth_session.id,
                details={"reason": RevocationReason.IDLE_TIMEOUT.value},
            )
            raise AuthenticationError(INVALID_TOKEN)
        if now - auth_session.last_seen_at >= LAST_SEEN_RESOLUTION:
            auth_session.last_seen_at = now
            self._session.commit()
        is_superuser, grants, role_ids = self._users.effective_grants(user.id)
        permissions: dict[str, Scope] = {}
        for code, scope in grants:  # broadest scope wins across roles
            scope = Scope(scope)
            if code not in permissions or SCOPE_RANK[scope] > SCOPE_RANK[permissions[code]]:
                permissions[code] = scope
        return Principal(
            user_id=user.id,
            staff_id=user.staff_id,
            username=user.username,
            permissions=permissions,
            is_superuser=is_superuser,
            session_id=auth_session.id,
            role_ids=frozenset(role_ids),
        )

    def _idle_expired(self, auth_session: AuthSession, now: datetime) -> bool:
        return now - auth_session.last_seen_at > timedelta(minutes=self._settings.auth_idle_timeout_minutes)

    # --- logout / password -----------------------------------------------------------------

    def logout(self, principal: Principal) -> None:
        auth_session = self._sessions.get(principal.session_id)
        if auth_session is not None and auth_session.revoked_at is None:
            auth_session.revoked_at = utc_now()
            auth_session.revocation_reason = RevocationReason.LOGOUT.value
            self._session.commit()
        self._audit.record("auth.logout", AuditOutcome.SUCCESS, principal=principal,
                           resource_type="sessions", resource_id=principal.session_id)

    def logout_everywhere(self, principal: Principal) -> int:
        count = self._sessions.revoke_for_user(principal.user_id, utc_now(), RevocationReason.LOGOUT_ALL.value)
        self._session.commit()
        self._audit.record("auth.logout_all", AuditOutcome.SUCCESS, principal=principal,
                           resource_type="users", resource_id=principal.user_id, details={"sessions_revoked": count})
        return count

    def change_password(self, principal: Principal, current_password: str, new_password: str) -> None:
        user = self._users.get(principal.user_id, for_update=True)
        if not verify_password(current_password, user.password_hash):
            self._session.rollback()
            self._audit.record("auth.password_change", AuditOutcome.FAILURE, principal=principal,
                               resource_type="users", resource_id=principal.user_id,
                               details={"reason": "current_password_incorrect"})
            raise BusinessValidationError("current_password is incorrect", field="current_password")
        try:
            check_password_policy(new_password, username=user.username)
        except ValueError as exc:
            raise BusinessValidationError(str(exc), field="new_password") from None
        now = utc_now()
        user.password_hash = hash_password(new_password)
        user.password_changed_at = now
        revoked = self._sessions.revoke_for_user(user.id, now, RevocationReason.PASSWORD_CHANGE.value,
                                                 except_session_id=principal.session_id)
        self._session.commit()
        self._audit.record("auth.password_change", AuditOutcome.SUCCESS, principal=principal,
                           resource_type="users", resource_id=principal.user_id,
                           details={"other_sessions_revoked": revoked})

    def me(self, principal: Principal) -> MeRead:
        user = self._users.get(principal.user_id)
        staff = self._staff.get(user.staff_id)
        roles = [r.name for r in self._users.roles(user.id) if r.status == RecordStatus.ACTIVE]
        return MeRead(
            user_id=user.id,
            username=user.username,
            staff=staff,
            roles=roles,
            is_superuser=principal.is_superuser,
            permissions=sorted(
                ({"code": code, "scope": scope} for code, scope in principal.permissions.items()),
                key=lambda g: g["code"],
            ),
        )
