"""Stage 5 unit tests: password hashing, tokens, principal, permission catalog, route coverage."""

import secrets
import uuid

import pytest
from fastapi.routing import APIRoute

from app.api.auth import get_principal
from app.core import security
from app.core.config import load_settings
from app.core.permissions import DEFAULT_ROLES, DESCRIPTIONS, SUPER_ADMIN, TIMELINE_EVENT_PERMISSIONS, P, Scope
from app.core.principal import Principal
from app.factory import create_app
from app.schemas.auth import ChangePasswordRequest, PermissionGrant, RoleCreate, UserCreate
from app.schemas.timeline import TimelineEventType


def pw() -> str:
    return "Tq7-" + secrets.token_urlsafe(16)


# --- password hashing ------------------------------------------------------------------------


def test_hash_format_and_verification():
    password = pw()
    encoded = security.hash_password(password)
    prefix, log2_n, r, p, salt, key = encoded.split("$")
    assert (prefix, int(log2_n), int(r), int(p)) == ("scrypt", 14, 8, 5)
    assert password not in encoded
    assert security.verify_password(password, encoded)
    assert not security.verify_password(password + "x", encoded)
    assert not security.verify_password("", encoded)


def test_hashes_are_salted():
    password = pw()
    assert security.hash_password(password) != security.hash_password(password)


@pytest.mark.parametrize("encoded", ["", "plaintext", "bcrypt$x$y", "scrypt$14$8$5$@@@$@@@", "scrypt$99$8$5$AA==$AA==",
                                     "scrypt$a$b$c$d$e"])
def test_malformed_hashes_never_verify(encoded):
    assert not security.verify_password("anything", encoded)


def test_needs_rehash_for_weaker_parameters():
    password = pw()
    assert not security.needs_rehash(security.hash_password(password))
    salt = b"0123456789abcdef"
    weak = security._derive(password, salt, 10, 8, 1)
    old = f"scrypt$10$8$1${security._b64(salt)}${security._b64(weak)}"
    assert security.verify_password(password, old) and security.needs_rehash(old)
    assert security.needs_rehash("garbage")


@pytest.mark.parametrize(("candidate", "message"), [
    ("short1A!", "at least 12"), ("x" * 129, "at most 128"), (" leading-space-pw1", "whitespace"),
    ("aaaaaaaaaaaaaaaa", "repetitive"), ("my-username-is-in-here", "username"),
])
def test_password_policy(candidate, message):
    with pytest.raises(ValueError, match=message):
        security.check_password_policy(candidate, username="username")


def test_password_policy_accepts_strong_passwords():
    security.check_password_policy(pw(), username="someone")


def test_tokens_are_random_and_only_digests_are_stored():
    a, b = security.new_session_token(), security.new_session_token()
    assert a != b and len(a) >= 43
    digest = security.token_digest(a)
    assert len(digest) == 64 and a not in digest and security.token_digest(a) == digest


# --- schemas ---------------------------------------------------------------------------------------


def test_user_create_validation():
    staff_id = str(uuid.uuid4())
    user = UserCreate(staff_id=staff_id, username=" Nurse.Jane ", password=pw())
    assert user.username == "nurse.jane"
    with pytest.raises(ValueError):
        UserCreate(staff_id=staff_id, username="ab", password=pw())
    with pytest.raises(ValueError):
        UserCreate(staff_id=staff_id, username="bad name", password=pw())
    # Candidate passwords are built at runtime: the repository must contain no password literals.
    with pytest.raises(ValueError, match="username"):
        UserCreate(staff_id=staff_id, username="janedoe", password="xX-" + "janedoe" + secrets.token_hex(6))
    with pytest.raises(ValueError, match="at least 12"):
        UserCreate(staff_id=staff_id, username="janedoe", password=secrets.token_hex(3))


def test_change_password_must_differ():
    same = pw()
    with pytest.raises(ValueError, match="differ"):
        ChangePasswordRequest(current_password=same, new_password=same)


def test_role_and_grant_normalization():
    role = RoleCreate(name=" triage_nurse ", permissions=[{"code": "Observation.Create"}])
    assert role.name == "TRIAGE_NURSE" and role.permissions[0].code == "observation.create"
    assert role.permissions[0].scope == Scope.ALL
    for bad in ({"name": "1ROLE"}, {"name": "role name"}, {"name": "X"}):
        with pytest.raises(ValueError):
            RoleCreate(**bad)
    with pytest.raises(ValueError):
        PermissionGrant(code="patient")
    with pytest.raises(ValueError):
        PermissionGrant(code="patient.view", scope="DEPARTMENT")  # reserved, not yet valid


# --- principal ------------------------------------------------------------------------------------


def test_principal_permissions_and_scope():
    staff_id = uuid.uuid4()
    p = Principal(user_id=uuid.uuid4(), staff_id=staff_id, username="n",
                  permissions={"workflow.view": Scope.OWN, "patient.view": Scope.ALL})
    assert p.has(P.PATIENT_VIEW) and p.has("workflow.view") and not p.has(P.PATIENT_CREATE)
    assert p.scope(P.WORKFLOW_VIEW) == Scope.OWN and p.scope(P.PATIENT_CREATE) is None
    assert p.own_staff_filter(P.WORKFLOW_VIEW) == staff_id
    assert p.own_staff_filter(P.PATIENT_VIEW) is None
    superuser = Principal(user_id=None, staff_id=None, username="root", is_superuser=True)
    assert superuser.has(P.ROLE_MANAGE) and superuser.scope(P.WORKFLOW_VIEW) == Scope.ALL


def test_own_scope_without_staff_matches_nothing():
    p = Principal(user_id=None, staff_id=None, username="x", permissions={"workflow.view": Scope.OWN})
    assert isinstance(p.own_staff_filter(P.WORKFLOW_VIEW), uuid.UUID)


# --- catalog ----------------------------------------------------------------------------------------


def test_catalog_is_complete_and_well_formed():
    assert set(DESCRIPTIONS) == set(P)
    assert len({p.value for p in P}) == len(P)
    for p in P:
        assert p.value.count(".") == 1 and p.value == p.value.lower()
    for required in ("patient.view", "patient.create", "patient.edit", "encounter.view", "encounter.create",
                     "encounter.edit", "observation.view", "observation.create", "report.view", "report.create",
                     "report.verify", "prescription.view", "prescription.create", "staff.view", "staff.manage",
                     "workflow.view", "workflow.manage", "ai.analysis", "ai.review", "audit.view", "role.manage",
                     "permission.manage"):
        assert required in {p.value for p in P}


def test_every_timeline_event_type_is_permission_mapped():
    assert set(TIMELINE_EVENT_PERMISSIONS) == {t.value for t in TimelineEventType}


def test_default_roles():
    assert set(DEFAULT_ROLES) == {"SUPER_ADMIN", "DOCTOR", "NURSE", "RECEPTIONIST", "LAB_TECHNICIAN", "PHARMACIST"}
    assert DEFAULT_ROLES[SUPER_ADMIN][1] == {}  # implicit: every permission
    doctor, nurse, reception = (DEFAULT_ROLES[r][1] for r in ("DOCTOR", "NURSE", "RECEPTIONIST"))
    assert P.PRESCRIPTION_CREATE in doctor and P.PRESCRIPTION_CREATE not in nurse
    assert nurse[P.WORKFLOW_VIEW] == Scope.OWN
    assert P.ENCOUNTER_VIEW not in reception and P.CLINICAL_NOTE_VIEW not in reception
    for _, grants in DEFAULT_ROLES.values():  # nobody but SUPER_ADMIN manages access
        assert not {P.ROLE_MANAGE, P.PERMISSION_MANAGE, P.USER_MANAGE} & set(grants)


# --- every API route is protected --------------------------------------------------------------------


PUBLIC = {("POST", "/api/auth/login")}
AUTHENTICATED_ONLY = {("GET", "/api/auth/me"), ("POST", "/api/auth/logout"), ("POST", "/api/auth/logout-all"),
                      ("POST", "/api/auth/change-password")}


def _dependency_calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _dependency_calls(dep)


def _walk(routes):
    """FastAPI >= 0.13x wraps included routers lazily (_IncludedRouter); descend into them."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _walk(route.original_router.routes)


def api_routes(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://hms_app:change-me@127.0.0.1:1/hms_dev")
    app = create_app(load_settings(_env_file=None))
    found = []
    for route in _walk(app.routes):
        if route.path.startswith("/api"):
            for method in route.methods:
                found.append((method, route.path, list(_dependency_calls(route.dependant))))
    # Guard against a vacuous pass: the walk must see every documented operation.
    documented = sum(len(ops) for path, ops in app.openapi()["paths"].items() if path.startswith("/api"))
    assert len(found) == documented and documented > 100
    return found


def test_every_api_route_requires_a_permission_or_authentication(monkeypatch):
    unprotected = []
    for method, path, calls in api_routes(monkeypatch):
        if (method, path) in PUBLIC:
            assert get_principal not in calls
            continue
        needs_permission = any(getattr(call, "required_permissions", None) for call in calls)
        if (method, path) in AUTHENTICATED_ONLY:
            assert get_principal in calls, (method, path)
        elif not needs_permission:
            unprotected.append(f"{method} {path}")
    assert unprotected == []


def test_route_permissions_come_from_the_catalog(monkeypatch):
    used = set()
    for _, _, calls in api_routes(monkeypatch):
        for call in calls:
            used |= set(getattr(call, "required_permissions", ()))
    assert used <= set(P)
    reserved = set()  # Stage 8: ai.review now guards the AI review pathway
    assert set(P) - used == reserved  # every permission guards at least one route
