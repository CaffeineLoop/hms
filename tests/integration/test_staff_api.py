"""Departments and staff API against hms_test, plus the Stage 4 'no authorization yet' boundary."""

import uuid

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]


def ok(response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


# --- departments ------------------------------------------------------------------------------


def test_department_crud(client):
    response = client.post("/api/departments", json={"name": " Internal Medicine ", "description": "Adult medicine"})
    dept = ok(response, 201)
    assert response.headers["Location"] == f"/api/departments/{dept['id']}"
    assert dept["name"] == "Internal Medicine" and dept["status"] == "ACTIVE"
    assert ok(client.get(f"/api/departments/{dept['id']}")) == dept
    renamed = ok(client.patch(f"/api/departments/{dept['id']}", json={"name": "General Medicine", "description": None}))
    assert renamed["name"] == "General Medicine" and renamed["description"] is None


def test_department_names_are_unique_case_insensitively(client, make_department):
    make_department(name="Pediatrics")
    assert client.post("/api/departments", json={"name": "PEDIATRICS"}).status_code == 409
    other = make_department(name="Surgery")
    assert client.patch(f"/api/departments/{other['id']}", json={"name": "pediatrics"}).status_code == 409


def test_department_deactivate_reactivate(client, make_department):
    dept = make_department()
    assert ok(client.post(f"/api/departments/{dept['id']}/deactivate"))["status"] == "INACTIVE"
    assert client.post(f"/api/departments/{dept['id']}/deactivate").status_code == 409
    assert ok(client.post(f"/api/departments/{dept['id']}/reactivate"))["status"] == "ACTIVE"
    assert client.post(f"/api/departments/{dept['id']}/reactivate").status_code == 409


def test_list_departments(client, make_department):
    make_department(name="Radiology")
    b = make_department(name="Maternity")
    ok(client.post(f"/api/departments/{b['id']}/deactivate"))
    body = ok(client.get("/api/departments"))
    assert [d["name"] for d in body["items"]] == ["Maternity", "Radiology"] and body["total"] == 2
    assert ok(client.get("/api/departments", params={"status": "ACTIVE"}))["total"] == 1
    assert ok(client.get("/api/departments", params={"q": "radio"}))["items"][0]["name"] == "Radiology"


# --- staff ---------------------------------------------------------------------------------------


def test_staff_crud(client, make_department):
    dept = make_department()
    response = client.post("/api/staff", json={
        "employee_code": " emp-0001 ", "first_name": "Achieng", "last_name": "Otieno", "designation": "DOCTOR",
        "department_id": dept["id"], "phone": "+254 700 000 001", "email": "A.Otieno@Hospital.org"})
    staff = ok(response, 201)
    assert response.headers["Location"] == f"/api/staff/{staff['id']}"
    assert staff["employee_code"] == "EMP-0001" and staff["full_name"] == "Achieng Otieno"
    assert staff["email"] == "a.otieno@hospital.org" and staff["phone"] == "+254700000001"
    assert staff["status"] == "ACTIVE" and staff["deactivated_at"] is None
    assert ok(client.get(f"/api/staff/{staff['id']}")) == staff

    other = make_department(name="Surgery")
    updated = ok(client.patch(f"/api/staff/{staff['id']}", json={"designation": "CLINICAL_OFFICER",
                                                                 "department_id": other["id"], "phone": None}))
    assert updated["designation"] == "CLINICAL_OFFICER" and updated["department_id"] == other["id"]
    assert updated["phone"] is None and updated["employee_code"] == "EMP-0001"


def test_staff_uniqueness(client, make_staff, make_department):
    dept = make_department()
    first = make_staff(dept, employee_code="EMP-0100", email="nurse@hospital.org")
    body = {"employee_code": "emp-0100", "first_name": "A", "last_name": "B", "designation": "NURSE",
            "department_id": dept["id"]}
    assert client.post("/api/staff", json=body).status_code == 409
    response = client.post("/api/staff", json={**body, "employee_code": "EMP-0101", "email": "NURSE@hospital.org"})
    assert response.status_code == 409
    second = make_staff(dept)
    assert client.patch(f"/api/staff/{second['id']}", json={"email": "nurse@hospital.org"}).status_code == 409
    assert client.patch(f"/api/staff/{first['id']}", json={"employee_code": "X-1"}).status_code == 422


def test_staff_department_references(client, make_department):
    body = {"employee_code": "EMP-0200", "first_name": "A", "last_name": "B", "designation": "NURSE"}
    response = client.post("/api/staff", json={**body, "department_id": str(uuid.uuid4())})
    assert response.status_code == 422 and response.json()["detail"][0]["loc"] == ["body", "department_id"]
    dept = make_department()
    ok(client.post(f"/api/departments/{dept['id']}/deactivate"))
    assert client.post("/api/staff", json={**body, "department_id": dept["id"]}).status_code == 409


def test_staff_deactivate_reactivate(client, make_staff):
    staff = make_staff()
    off = ok(client.post(f"/api/staff/{staff['id']}/deactivate"))
    assert off["status"] == "INACTIVE" and off["deactivated_at"]
    assert client.post(f"/api/staff/{staff['id']}/deactivate").status_code == 409
    on = ok(client.post(f"/api/staff/{staff['id']}/reactivate"))
    assert on["status"] == "ACTIVE" and on["deactivated_at"] is None


def test_reactivation_needs_active_department(client, make_staff, make_department):
    dept = make_department()
    staff = make_staff(dept)
    ok(client.post(f"/api/staff/{staff['id']}/deactivate"))
    ok(client.post(f"/api/departments/{dept['id']}/deactivate"))
    assert client.post(f"/api/staff/{staff['id']}/reactivate").status_code == 409


def test_list_and_search_staff(client, make_staff, make_department):
    dept = make_department()
    make_staff(dept, first_name="Zawadi", last_name="Kiprono", designation="NURSE")
    make_staff(dept, employee_code="LAB-TECH-1", first_name="Brian", last_name="Mutua", designation="LAB_TECHNICIAN")
    make_staff(first_name="Carol", last_name="Achieng")
    body = ok(client.get("/api/staff"))
    assert [s["last_name"] for s in body["items"]] == ["Achieng", "Kiprono", "Mutua"]
    assert ok(client.get("/api/staff", params={"department_id": dept["id"]}))["total"] == 2
    assert ok(client.get("/api/staff", params={"designation": "LAB_TECHNICIAN"}))["items"][0]["first_name"] == "Brian"
    assert ok(client.get("/api/staff", params={"q": "lab-tech"}))["total"] == 1
    assert ok(client.get("/api/staff", params={"q": "zawadi kip"}))["total"] == 1
    assert ok(client.get("/api/staff", params={"q": "%"}))["total"] == 0


@pytest.mark.parametrize("path", ["departments", "staff"])
def test_missing_invalid_and_no_delete(client, path):
    assert client.get(f"/api/{path}/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/api/{path}/nope").status_code == 422
    assert client.patch(f"/api/{path}/{uuid.uuid4()}", json={"first_name": "x"} if path == "staff" else {"name": "x"}).status_code == 404
    assert client.post(f"/api/{path}/{uuid.uuid4()}/deactivate").status_code == 404
    assert client.delete(f"/api/{path}/{uuid.uuid4()}").status_code == 405


# --- designation vs. authorization ---------------------------------------------------------------
# Stage 4 asserted that authorization was not enforced yet (no security schemes, credentials
# ignored). Stage 5 intentionally replaced that: see tests/integration/test_authorization.py.


def test_designation_grants_nothing(client, make_staff, patient_payload):
    """Designation is descriptive: permissions come from roles (Stage 5), not from the job title."""
    receptionist = make_staff(designation="RECEPTIONIST")
    patient = ok(client.post("/api/patients", json=patient_payload()), 201)
    encounter = ok(client.post(f"/api/patients/{patient['id']}/encounters",
                               json={"encounter_type": "OPD", "reason": "x"}), 201)
    note = ok(client.post(f"/api/patients/{patient['id']}/clinical-notes", json={
        "encounter_id": encounter["id"], "note_type": "OTHER", "author_staff_id": receptionist["id"],
        "content": "x"}), 201)
    assert note["author_staff_id"] == receptionist["id"]
