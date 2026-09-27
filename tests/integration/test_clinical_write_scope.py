"""Clinical write authorization (UI-3 hardening): every patient clinical-record write needs its write permission at
ALL scope. OWN grants no record-level access to clinical records, so an OWN-only grant is refused by the backend
(403) before anything is looked up or changed. Default roles are unaffected.

Endpoints: POST /patients/{id}/encounters, POST /encounters/{id}/start|finish|cancel, POST /patients/{id}/observations,
POST /patients/{id}/conditions, PATCH /conditions/{id}, POST /patients/{id}/allergies, PATCH /allergies/{id},
POST /patients/{id}/clinical-notes.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]

WRITE_PERMISSIONS = ["encounter.create", "encounter.edit", "observation.create", "condition.create", "condition.edit",
                     "allergy.create", "allergy.edit", "clinical_note.create"]
READ_PERMISSIONS = ["patient.view", "encounter.view", "observation.view", "condition.view", "allergy.view", "clinical_note.view"]
MARKER = "Marker-w7c2"


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def now(minutes: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()


@pytest.fixture
def since(test_engine):
    with test_engine.connect() as c:
        return c.execute(text("SELECT clock_timestamp()")).scalar_one()


@pytest.fixture
def events(test_engine, since):
    def fetch(**filters) -> list[dict]:
        clauses = " ".join(f"AND {k} = :{k}" for k in filters)
        with test_engine.connect() as c:
            rows = c.execute(text(f"SELECT * FROM audit_events WHERE occurred_at >= :since {clauses} "
                                  "ORDER BY occurred_at, id"), {"since": since, **filters}).mappings().all()
        return [dict(r) for r in rows]

    return fetch


@pytest.fixture
def chart(client, patient_payload) -> dict:
    """Patient A: an in-progress and a planned encounter, a condition, an allergy. Patient B: an encounter."""
    a = ok(client.post("/api/patients", json=patient_payload(first_name="Alpha", date_of_birth="1970-01-01")), 201)
    b = ok(client.post("/api/patients", json=patient_payload(first_name="Bravo", date_of_birth="1971-01-01")), 201)

    def enc(p, **extra):
        return ok(client.post(f"/api/patients/{p['id']}/encounters", json={"encounter_type": "OPD", "reason": "Review", **extra}), 201)

    return {
        "a": a, "b": b, "enc": enc(a), "planned": enc(a, status="PLANNED", start_at=now(60 * 24)), "b_enc": enc(b),
        "condition": ok(client.post(f"/api/patients/{a['id']}/conditions", json={"name": "Hypertension", "status": "SUSPECTED"}), 201),
        "allergy": ok(client.post(f"/api/patients/{a['id']}/allergies", json={"substance": "Penicillin"}), 201),
    }


def writes(chart: dict) -> list[tuple[str, str, str, dict, str]]:
    """(name, method, path, body, permission) for every clinical write, against patient A's records."""
    a, e = chart["a"]["id"], chart["enc"]["id"]
    return [
        ("create encounter", "POST", f"/api/patients/{a}/encounters", {"encounter_type": "OPD", "reason": MARKER}, "encounter.create"),
        ("start encounter", "POST", f"/api/encounters/{chart['planned']['id']}/start", {}, "encounter.edit"),
        ("finish encounter", "POST", f"/api/encounters/{e}/finish", {"summary": MARKER}, "encounter.edit"),
        ("cancel encounter", "POST", f"/api/encounters/{chart['planned']['id']}/cancel", {"reason": MARKER}, "encounter.edit"),
        ("record observation", "POST", f"/api/patients/{a}/observations",
         {"code": "heart_rate", "value_numeric": 80, "unit": "/min", "effective_at": now(), "notes": MARKER}, "observation.create"),
        ("add condition", "POST", f"/api/patients/{a}/conditions", {"name": MARKER}, "condition.create"),
        ("update condition", "PATCH", f"/api/conditions/{chart['condition']['id']}", {"status": "ACTIVE", "notes": MARKER}, "condition.edit"),
        ("add allergy", "POST", f"/api/patients/{a}/allergies", {"substance": MARKER}, "allergy.create"),
        ("update allergy", "PATCH", f"/api/allergies/{chart['allergy']['id']}", {"severity": "SEVERE", "notes": MARKER}, "allergy.edit"),
        ("write note", "POST", f"/api/patients/{a}/clinical-notes", {"encounter_id": e, "note_type": "PROGRESS", "content": MARKER},
         "clinical_note.create"),
    ]


def state(client, chart) -> str:
    """Everything patient A's writes could change, as one comparable snapshot."""
    a = chart["a"]["id"]
    parts = [client.get(f"/api/patients/{a}/{c}", params={"limit": 100}).json()["items"]
             for c in ("encounters", "observations", "conditions", "allergies", "clinical-notes")]
    return json.dumps(parts, sort_keys=True, default=str)


def make_role(client, name: str, scope: str) -> None:
    grants = [{"code": c, "scope": scope} for c in WRITE_PERMISSIONS] + [{"code": c} for c in READ_PERMISSIONS]
    ok(client.post("/api/roles", json={"name": name, "permissions": grants}), 201)


def call(auth_client, user, method, path, body):
    return auth_client.request(method, path, json=body, headers=user["headers"])


# --- OWN scope is refused by the backend; ALL scope is allowed -------------------------------------------------


def test_own_scoped_clinical_write_permissions_are_rejected_and_change_nothing(auth_client, client, make_user, chart):
    make_role(client, "WRITE_OWN", "OWN")
    user = make_user("WRITE_OWN")
    before = state(client, chart)
    for name, method, path, body, permission in writes(chart):
        response = call(auth_client, user, method, path, body)
        assert response.status_code == 403, (name, response.status_code, response.text)
        detail = response.json()["detail"]
        assert permission in detail and "OWN" in detail, (name, detail)
        assert MARKER not in response.text
    assert state(client, chart) == before


def test_own_scope_rejection_happens_before_any_lookup(auth_client, client, make_user):
    make_role(client, "WRITE_OWN_UNKNOWN", "OWN")
    user = make_user("WRITE_OWN_UNKNOWN")
    unknown = uuid.uuid4()
    for method, path in (("POST", f"/api/encounters/{unknown}/finish"), ("PATCH", f"/api/conditions/{unknown}"),
                         ("PATCH", f"/api/allergies/{unknown}"), ("POST", f"/api/patients/{unknown}/observations")):
        response = call(auth_client, user, method, path, {})
        assert response.status_code == 403, (path, response.status_code)  # not 404/422: no existence oracle


def test_the_same_permissions_at_all_scope_are_allowed(auth_client, client, make_user, chart):
    make_role(client, "WRITE_ALL", "ALL")
    user = make_user("WRITE_ALL")
    for name, method, path, body, _ in writes(chart):
        response = call(auth_client, user, method, path, body)
        assert response.status_code in (200, 201), (name, response.status_code, response.text)


def test_own_on_one_permission_blocks_only_that_write(auth_client, client, make_user, chart):
    grants = [{"code": c} for c in WRITE_PERMISSIONS + READ_PERMISSIONS if c != "observation.create"]
    ok(client.post("/api/roles", json={"name": "OBS_OWN", "permissions": grants + [{"code": "observation.create", "scope": "OWN"}]}), 201)
    user = make_user("OBS_OWN")
    a = chart["a"]["id"]
    obs = call(auth_client, user, "POST", f"/api/patients/{a}/observations",
               {"code": "heart_rate", "value_numeric": 80, "unit": "/min", "effective_at": now()})
    assert obs.status_code == 403
    assert call(auth_client, user, "POST", f"/api/patients/{a}/conditions", {"name": "Asthma"}).status_code == 201


# --- default roles unchanged ---------------------------------------------------------------------------------


EXPECTED = {
    # Doctor holds every clinical write at ALL.
    "DOCTOR": dict.fromkeys(WRITE_PERMISSIONS, "allowed"),
    # Nurse: observations, allergy.create and notes (ALL); no encounter/condition writes, no allergy.edit.
    "NURSE": {"encounter.create": 403, "encounter.edit": 403, "observation.create": "allowed", "condition.create": 403,
              "condition.edit": 403, "allergy.create": "allowed", "allergy.edit": 403, "clinical_note.create": "allowed"},
    "RECEPTIONIST": dict.fromkeys(WRITE_PERMISSIONS, 403),
}


@pytest.mark.parametrize("role", list(EXPECTED))
def test_default_roles_keep_their_clinical_write_behaviour(auth_client, make_user, chart, role):
    user = make_user(role)
    for name, method, path, body, permission in writes(chart):
        response = call(auth_client, user, method, path, body)
        expected = EXPECTED[role][permission]
        if expected == "allowed":
            assert response.status_code in (200, 201), (role, name, response.status_code, response.text)
        else:
            assert response.status_code == 403, (role, name, response.status_code)
            assert response.json()["detail"] == f"Missing permission: {permission}."


# --- cross-patient writes stay blocked; authorship and audit unchanged -------------------------------------------


def test_cross_patient_writes_remain_blocked(auth_client, client, make_user, chart):
    doctor = make_user("DOCTOR")
    a, b = chart["a"]["id"], chart["b"]["id"]
    before_a, before_b = state(client, chart), client.get(f"/api/patients/{b}/observations").json()["total"]
    for path, body in ((f"/api/patients/{a}/observations",
                        {"code": "heart_rate", "value_numeric": 80, "unit": "/min", "effective_at": now(), "encounter_id": chart["b_enc"]["id"]}),
                       (f"/api/patients/{a}/clinical-notes", {"encounter_id": chart["b_enc"]["id"], "note_type": "PROGRESS", "content": MARKER}),
                       (f"/api/patients/{a}/conditions", {"name": MARKER, "encounter_id": chart["b_enc"]["id"]})):
        response = call(auth_client, doctor, "POST", path, body)
        assert response.status_code == 422, (path, response.status_code, response.text)
    assert state(client, chart) == before_a
    assert client.get(f"/api/patients/{b}/observations").json()["total"] == before_b


def test_authorship_binding_is_unchanged(auth_client, make_user, chart):
    doctor, nurse = make_user("DOCTOR"), make_user("NURSE")
    a, e = chart["a"]["id"], chart["enc"]["id"]
    note = ok(call(auth_client, nurse, "POST", f"/api/patients/{a}/clinical-notes",
                   {"encounter_id": e, "note_type": "NURSING", "content": "Observed"}), 201)
    assert note["author_staff_id"] == nurse["staff"]["id"] and note["author_name"] == nurse["staff"]["full_name"]
    impersonation = call(auth_client, nurse, "POST", f"/api/patients/{a}/clinical-notes",
                         {"encounter_id": e, "note_type": "NURSING", "content": "x", "author_staff_id": doctor["staff"]["id"]})
    free_text = call(auth_client, nurse, "POST", f"/api/patients/{a}/clinical-notes",
                     {"encounter_id": e, "note_type": "NURSING", "content": "x", "author_name": "Someone Else"})
    assert impersonation.status_code == 403 and free_text.status_code == 403


def test_audit_records_allowed_and_own_denied_writes_without_content(auth_client, client, make_user, chart, events):
    doctor = make_user("DOCTOR")
    make_role(client, "WRITE_OWN_AUDIT", "OWN")
    limited = make_user("WRITE_OWN_AUDIT")
    a = chart["a"]["id"]
    ok(call(auth_client, doctor, "POST", f"/api/patients/{a}/conditions", {"name": MARKER}), 201)
    assert call(auth_client, limited, "POST", f"/api/patients/{a}/conditions", {"name": MARKER}).status_code == 403
    assert call(auth_client, limited, "PATCH", f"/api/allergies/{chart['allergy']['id']}", {"notes": MARKER}).status_code == 403

    rows = events(action="POST /api/patients/{patient_id}/conditions")
    allowed = [e for e in rows if str(e["actor_user_id"]) == doctor["user"]["id"]]
    denied = [e for e in rows if str(e["actor_user_id"]) == limited["user"]["id"]]
    assert len(allowed) == 1 and allowed[0]["outcome"] == "SUCCESS" and str(allowed[0]["patient_id"]) == a
    assert str(allowed[0]["actor_staff_id"]) == doctor["staff"]["id"]
    assert len(denied) == 1 and denied[0]["outcome"] == "DENIED" and denied[0]["status_code"] == 403
    [patch_denied] = [e for e in events(action="PATCH /api/allergies/{allergy_id}") if str(e["actor_user_id"]) == limited["user"]["id"]]
    assert patch_denied["outcome"] == "DENIED"
    assert MARKER not in json.dumps(events(), default=str)
