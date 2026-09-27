"""Encounter detail isolation (post UI-1 review): reading one encounter enforces patient scope in the backend.

- GET /api/encounters/{id} and GET /api/patients/{patient_id}/encounters/{id} need encounter.view AND
  patient.view, both at ALL scope (OWN grants no record-level access to clinical records). The check runs
  before any lookup, so a denied caller learns nothing - not even whether the id exists.
- The patient-scoped read only returns an encounter of that patient; another patient's encounter is the same
  404 as an unknown id, with none of that chart's data in the response.
"""

import json
import uuid

import pytest
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]

SECRET_REASON = "Confidential reason 7f3c"
SECRET_SUMMARY = "Confidential summary 91ab"
SCOPE_DENIED = "You are not permitted to view patients' clinical records."


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def as_(auth_client, user, path):
    return auth_client.get(path, headers=user["headers"])


@pytest.fixture
def since(test_engine):
    with test_engine.connect() as c:
        return c.execute(text("SELECT clock_timestamp()")).scalar_one()


@pytest.fixture
def events(test_engine, since):
    """Audit rows written since the test started, oldest first, as dicts."""

    def fetch(**filters) -> list[dict]:
        clauses = " ".join(f"AND {k} = :{k}" for k in filters)
        with test_engine.connect() as c:
            rows = c.execute(text(f"SELECT * FROM audit_events WHERE occurred_at >= :since {clauses} "
                                  "ORDER BY occurred_at, id"), {"since": since, **filters}).mappings().all()
        return [dict(r) for r in rows]

    return fetch


@pytest.fixture
def charts(client, patient_payload) -> dict:
    """Patient A with an encounter, and patient B whose encounter carries identifiable text."""
    a = ok(client.post("/api/patients", json=patient_payload(first_name="Alpha")), 201)
    b = ok(client.post("/api/patients", json=patient_payload(first_name="Bravo")), 201)
    enc_a = ok(client.post(f"/api/patients/{a['id']}/encounters", json={"encounter_type": "OPD", "reason": "Review"}), 201)
    enc_b = ok(client.post(f"/api/patients/{b['id']}/encounters",
                           json={"encounter_type": "OPD", "reason": SECRET_REASON, "summary": SECRET_SUMMARY}), 201)
    return {"a": a, "b": b, "enc_a": enc_a, "enc_b": enc_b}


def make_role(client, name: str, *grants: dict) -> None:
    ok(client.post("/api/roles", json={"name": name, "permissions": list(grants)}), 201)


def assert_no_leak(response, charts) -> None:
    b = charts["b"]
    for value in (SECRET_REASON, SECRET_SUMMARY, b["id"], b["first_name"], b["patient_number"]):
        assert value not in response.text, f"leaked {value!r}"


# --- legitimate access is preserved ----------------------------------------------------------------------


@pytest.mark.parametrize("role", ["DOCTOR", "NURSE", "SUPER_ADMIN"])
def test_authorized_roles_read_an_encounter_of_an_accessible_patient(auth_client, make_user, charts, role):
    user = make_user(role)
    a, enc = charts["a"], charts["enc_a"]
    by_id = ok(as_(auth_client, user, f"/api/encounters/{enc['id']}"))
    scoped = ok(as_(auth_client, user, f"/api/patients/{a['id']}/encounters/{enc['id']}"))
    assert by_id == scoped
    assert scoped["id"] == enc["id"] and scoped["patient_id"] == a["id"]
    assert set(scoped) == set(enc)  # response contract unchanged (EncounterRead)


# --- another patient's encounter -------------------------------------------------------------------------


def test_encounter_of_a_different_patient_is_denied_without_leaking(auth_client, make_user, charts):
    doctor = make_user("DOCTOR")
    a, enc_b = charts["a"], charts["enc_b"]
    response = as_(auth_client, doctor, f"/api/patients/{a['id']}/encounters/{enc_b['id']}")
    assert response.status_code == 404
    assert_no_leak(response, charts)
    # Indistinguishable from an id that does not exist at all.
    unknown = str(uuid.uuid4())
    missing = as_(auth_client, doctor, f"/api/patients/{a['id']}/encounters/{unknown}")
    assert missing.status_code == 404
    assert response.json()["detail"].replace(enc_b["id"], "X") == missing.json()["detail"].replace(unknown, "X")


def test_unknown_patient_in_the_scoped_path_is_404(auth_client, make_user, charts):
    doctor = make_user("DOCTOR")
    response = as_(auth_client, doctor, f"/api/patients/{uuid.uuid4()}/encounters/{charts['enc_b']['id']}")
    assert response.status_code == 404
    assert_no_leak(response, charts)


# --- callers outside patient scope -----------------------------------------------------------------------


@pytest.mark.parametrize(("name", "grants", "detail"), [
    ("ENC_PATIENT_OWN", [{"code": "encounter.view"}, {"code": "patient.view", "scope": "OWN"}], SCOPE_DENIED),
    ("ENC_OWN", [{"code": "encounter.view", "scope": "OWN"}, {"code": "patient.view"}], SCOPE_DENIED),
    ("ENC_NO_PATIENT", [{"code": "encounter.view"}], "Missing permission: patient.view."),
], ids=["patient-view-own", "encounter-view-own", "no-patient-view"])
def test_callers_without_patient_scope_are_denied_on_both_paths(auth_client, client, make_user, charts,
                                                                 name, grants, detail):
    make_role(client, name, *grants)
    user = make_user(name)
    b, enc_b = charts["b"], charts["enc_b"]
    for path in (f"/api/encounters/{enc_b['id']}", f"/api/patients/{b['id']}/encounters/{enc_b['id']}"):
        response = as_(auth_client, user, path)
        assert response.status_code == 403, path
        assert response.json()["detail"] == detail
        assert_no_leak(response, charts)
    # Checked before any lookup: an unknown id gets the same 403 (no existence oracle).
    unknown = as_(auth_client, user, f"/api/encounters/{uuid.uuid4()}")
    assert unknown.status_code == 403 and unknown.json()["detail"] == detail


def test_roles_without_encounter_view_are_still_denied(auth_client, make_user, charts):
    receptionist = make_user("RECEPTIONIST")
    a, enc_a = charts["a"], charts["enc_a"]
    for path in (f"/api/encounters/{enc_a['id']}", f"/api/patients/{a['id']}/encounters/{enc_a['id']}"):
        response = as_(auth_client, receptionist, path)
        assert response.status_code == 403
        assert response.json()["detail"] == "Missing permission: encounter.view."


# --- audit -----------------------------------------------------------------------------------------------


def test_encounter_reads_and_denials_are_audited(auth_client, client, make_user, charts, events):
    doctor = make_user("DOCTOR")
    make_role(client, "ENC_AUDIT_OWN", {"code": "encounter.view"}, {"code": "patient.view", "scope": "OWN"})
    limited = make_user("ENC_AUDIT_OWN")
    a, enc_a, enc_b = charts["a"], charts["enc_a"], charts["enc_b"]
    ok(as_(auth_client, doctor, f"/api/patients/{a['id']}/encounters/{enc_a['id']}"))
    assert as_(auth_client, doctor, f"/api/patients/{a['id']}/encounters/{enc_b['id']}").status_code == 404
    assert as_(auth_client, limited, f"/api/encounters/{enc_b['id']}").status_code == 403

    [read, mismatch] = events(action="GET /api/patients/{patient_id}/encounters/{encounter_id}")
    assert read["outcome"] == "SUCCESS" and read["status_code"] == 200
    assert read["resource_type"] == "encounters" and read["resource_id"] == enc_a["id"]
    assert str(read["patient_id"]) == a["id"] and str(read["actor_user_id"]) == doctor["user"]["id"]
    assert mismatch["status_code"] == 404 and str(mismatch["actor_user_id"]) == doctor["user"]["id"]
    [denied] = events(action="GET /api/encounters/{encounter_id}")
    assert denied["outcome"] == "DENIED" and denied["status_code"] == 403
    assert str(denied["actor_user_id"]) == limited["user"]["id"]
    dump = json.dumps(events(), default=str)
    assert SECRET_REASON not in dump and SECRET_SUMMARY not in dump
