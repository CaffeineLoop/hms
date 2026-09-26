"""Patient Management API end-to-end against the isolated test database (hms_test)."""

import re
import uuid
from datetime import date, timedelta

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]

FULL = {
    "first_name": "Amina",
    "middle_name": "Zawadi",
    "last_name": "Okafor",
    "date_of_birth": "1988-04-12",
    "sex": "FEMALE",
    "phone": "+254 712 345 678",
    "email": "Amina.Okafor@Example.org",
    "address_line1": "12 Riverside Drive",
    "address_line2": "Apt 4B",
    "city": "Nairobi",
    "state_province": "Nairobi County",
    "postal_code": "00100",
    "country": "Kenya",
    "emergency_contact_name": "Ben Okafor",
    "emergency_contact_relationship": "Brother",
    "emergency_contact_phone": "0722 000 111",
}


def create(client, **data):
    response = client.post("/api/patients", json=data)
    assert response.status_code == 201, response.text
    return response.json()


# --- create -----------------------------------------------------------------


def test_create_patient_with_all_fields(client):
    response = client.post("/api/patients", json=FULL)
    assert response.status_code == 201
    body = response.json()

    uuid.UUID(body["id"])
    assert re.fullmatch(r"PAT-\d{6}", body["patient_number"])
    assert response.headers["Location"] == f"/api/patients/{body['id']}"
    assert body["status"] == "ACTIVE"
    assert body["deactivated_at"] is None and body["deactivation_reason"] is None
    assert body["phone"] == "+254712345678"
    assert body["email"] == "amina.okafor@example.org"
    assert body["emergency_contact_phone"] == "0722000111"
    assert body["created_at"] and body["updated_at"]
    for field in ("first_name", "middle_name", "last_name", "date_of_birth", "sex", "city", "country"):
        assert body[field] == FULL[field]


def test_create_minimal_patient(client, patient_payload):
    body = create(client, **patient_payload())
    assert body["middle_name"] is None and body["phone"] is None and body["address_line1"] is None


def test_patient_numbers_are_unique_and_increasing(client, patient_payload):
    numbers = [
        create(client, **patient_payload(first_name=f"Patient{i}"))["patient_number"] for i in range(3)
    ]
    values = [int(n.removeprefix("PAT-")) for n in numbers]
    assert len(set(numbers)) == 3
    assert values == sorted(values)


def test_client_cannot_choose_patient_number_or_status(client, patient_payload):
    for extra in ({"patient_number": "PAT-000001"}, {"status": "INACTIVE"}, {"id": str(uuid.uuid4())}):
        assert client.post("/api/patients", json=patient_payload(**extra)).status_code == 422


def test_create_rejects_future_date_of_birth(client, patient_payload):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    response = client.post("/api/patients", json=patient_payload(date_of_birth=tomorrow))
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "date_of_birth"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"first_name": ""},
        {"last_name": "   "},
        {"sex": "F"},
        {"date_of_birth": "12/04/1988"},
        {"email": "not-an-email"},
        {"phone": "123"},
    ],
)
def test_create_rejects_invalid_input(client, patient_payload, overrides):
    assert client.post("/api/patients", json=patient_payload(**overrides)).status_code == 422


def test_create_rejects_missing_required_fields(client):
    response = client.post("/api/patients", json={})
    assert response.status_code == 422
    missing = {error["loc"][-1] for error in response.json()["detail"]}
    assert {"first_name", "last_name", "date_of_birth", "sex"} <= missing


def test_create_rejects_incomplete_emergency_contact(client, patient_payload):
    response = client.post("/api/patients", json=patient_payload(emergency_contact_name="Ben"))
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "emergency_contact_phone"]


def test_create_duplicate_patient_is_409(client, patient_payload):
    first = create(client, **patient_payload(phone="0712345678"))
    duplicate = patient_payload(first_name="AMINA", last_name="okafor", phone="0712-345-678")
    response = client.post("/api/patients", json=duplicate)
    assert response.status_code == 409
    assert first["patient_number"] in response.json()["detail"]


def test_same_name_and_dob_with_different_contact_is_allowed(client, patient_payload):
    create(client, **patient_payload(phone="0712345678"))
    create(client, **patient_payload(phone="0799999999"))
    create(client, **patient_payload())  # no contact details: cannot be flagged as a duplicate


def test_duplicate_detected_by_email(client, patient_payload):
    create(client, **patient_payload(email="amina@example.org"))
    response = client.post("/api/patients", json=patient_payload(email="AMINA@example.org"))
    assert response.status_code == 409


# --- retrieve ---------------------------------------------------------------


def test_get_patient(client):
    created = create(client, **FULL)
    response = client.get(f"/api/patients/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_patient_is_404(client):
    missing = uuid.uuid4()
    response = client.get(f"/api/patients/{missing}")
    assert response.status_code == 404
    assert response.json() == {"detail": f"Patient {missing} not found."}


def test_get_invalid_uuid_is_422(client):
    assert client.get("/api/patients/PAT-000001").status_code == 422


# --- list / search / filter / paginate --------------------------------------


@pytest.fixture
def roster(client, patient_payload):
    patients = [
        create(client, **patient_payload(first_name="Amina", last_name="Okafor", phone="0712345678",
                                         email="amina@example.org")),
        create(client, **patient_payload(first_name="Brian", middle_name="Kip", last_name="Otieno",
                                         date_of_birth="1975-09-30", sex="MALE", phone="+254733111222")),
        create(client, **patient_payload(first_name="Carla", last_name="Mendes", date_of_birth="2001-01-01",
                                         email="carla.m@clinic.test")),
        create(client, **patient_payload(first_name="Dmitri", last_name="O'Neil_Smith", sex="OTHER")),
    ]
    client.post(f"/api/patients/{patients[2]['id']}/deactivate", json={"reason": "Transferred"})
    return patients


def numbers(response) -> list[str]:
    return [p["patient_number"] for p in response.json()["items"]]


def test_list_returns_all_newest_first(client, roster):
    response = client.get("/api/patients")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4 and body["limit"] == 20 and body["offset"] == 0
    assert numbers(response) == [p["patient_number"] for p in reversed(roster)]


def test_list_empty(client):
    assert client.get("/api/patients").json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_pagination(client, roster):
    page1 = client.get("/api/patients", params={"limit": 2, "offset": 0})
    page2 = client.get("/api/patients", params={"limit": 2, "offset": 2})
    page3 = client.get("/api/patients", params={"limit": 2, "offset": 4})
    assert page1.json()["total"] == page2.json()["total"] == page3.json()["total"] == 4
    assert len(numbers(page1)) == 2 and len(numbers(page2)) == 2 and numbers(page3) == []
    assert set(numbers(page1)).isdisjoint(numbers(page2))
    assert set(numbers(page1)) | set(numbers(page2)) == {p["patient_number"] for p in roster}


def test_pagination_limits_are_enforced(client):
    assert client.get("/api/patients", params={"limit": 101}).status_code == 422
    assert client.get("/api/patients", params={"limit": 100}).status_code == 200


def test_filter_by_status(client, roster):
    active = client.get("/api/patients", params={"status": "ACTIVE"})
    inactive = client.get("/api/patients", params={"status": "INACTIVE"})
    assert active.json()["total"] == 3
    assert numbers(inactive) == [roster[2]["patient_number"]]
    assert client.get("/api/patients", params={"status": "active"}).status_code == 422


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("okafor", [0]),               # last name, case-insensitive
        ("BRI", [1]),                  # first-name prefix
        ("kip", [1]),                  # middle name
        ("amina okafor", [0]),         # full name
        ("Brian Kip Otieno", [1]),     # full name with middle
        ("0712345678", [0]),           # phone
        ("733 111", [1]),              # phone digits typed with spaces
        ("CLINIC.TEST", [2]),          # email
        ("amina@example.org", [0]),    # full email
        ("o'neil_", [3]),              # quote and literal underscore
        ("zzz-no-match", []),
    ],
)
def test_search(client, roster, query, expected):
    response = client.get("/api/patients", params={"q": query})
    assert response.status_code == 200
    assert sorted(numbers(response)) == sorted(roster[i]["patient_number"] for i in expected)
    assert response.json()["total"] == len(expected)


def test_search_by_patient_number(client, roster):
    target = roster[1]["patient_number"]
    response = client.get("/api/patients", params={"q": target})
    assert numbers(response) == [target]
    response = client.get("/api/patients", params={"q": target.lower()})
    assert numbers(response) == [target]


def test_search_wildcards_are_literal(client, roster):
    assert client.get("/api/patients", params={"q": "%"}).json()["total"] == 0
    assert client.get("/api/patients", params={"q": "_"}).json()["total"] == 1  # only O'Neil_Smith


def test_search_combined_with_status_and_pagination(client, roster):
    response = client.get("/api/patients", params={"q": "o", "status": "ACTIVE", "limit": 1})
    body = response.json()
    assert body["total"] == 3  # Okafor, Otieno, O'Neil_Smith; Mendes is inactive
    assert len(body["items"]) == 1


def test_blank_search_returns_everything(client, roster):
    assert client.get("/api/patients", params={"q": "   "}).json()["total"] == 4


# --- update -----------------------------------------------------------------


def test_patch_updates_only_given_fields(client):
    created = create(client, **FULL)
    response = client.patch(
        f"/api/patients/{created['id']}", json={"city": "Mombasa", "phone": "0700 111 222"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["city"] == "Mombasa" and body["phone"] == "0700111222"
    assert body["first_name"] == created["first_name"]
    assert body["patient_number"] == created["patient_number"]
    assert body["created_at"] == created["created_at"]
    assert body["updated_at"] > created["updated_at"]
    assert client.get(f"/api/patients/{created['id']}").json() == body


def test_patch_can_clear_optional_fields(client):
    created = create(client, **FULL)
    response = client.patch(
        f"/api/patients/{created['id']}",
        json={
            "middle_name": None,
            "email": None,
            "emergency_contact_name": None,
            "emergency_contact_phone": None,
            "emergency_contact_relationship": None,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["middle_name"] is None and body["email"] is None and body["emergency_contact_name"] is None


def test_patch_identity_fields(client, patient_payload):
    created = create(client, **patient_payload())
    response = client.patch(
        f"/api/patients/{created['id']}",
        json={"last_name": "Okafor-Ndiaye", "date_of_birth": "1988-04-21", "sex": "UNKNOWN"},
    )
    assert response.status_code == 200
    assert response.json()["last_name"] == "Okafor-Ndiaye"
    assert response.json()["sex"] == "UNKNOWN"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"first_name": None},
        {"first_name": ""},
        {"date_of_birth": (date.today() + timedelta(days=1)).isoformat()},
        {"status": "INACTIVE"},
        {"patient_number": "PAT-999999"},
        {"email": "bad"},
    ],
)
def test_patch_rejects_invalid_input(client, patient_payload, body):
    created = create(client, **patient_payload())
    response = client.patch(f"/api/patients/{created['id']}", json=body)
    assert response.status_code == 422
    assert client.get(f"/api/patients/{created['id']}").json() == created


def test_patch_rejects_breaking_emergency_contact(client):
    created = create(client, **FULL)
    response = client.patch(f"/api/patients/{created['id']}", json={"emergency_contact_phone": None})
    assert response.status_code == 422


def test_patch_missing_patient_is_404(client):
    assert client.patch(f"/api/patients/{uuid.uuid4()}", json={"city": "X"}).status_code == 404


def test_patch_into_duplicate_is_409(client, patient_payload):
    create(client, **patient_payload(phone="0712345678"))
    other = create(client, **patient_payload(first_name="Zainab", phone="0712345678"))
    response = client.patch(f"/api/patients/{other['id']}", json={"first_name": "amina"})
    assert response.status_code == 409


def test_patch_own_record_is_not_a_duplicate_of_itself(client, patient_payload):
    created = create(client, **patient_payload(phone="0712345678"))
    response = client.patch(f"/api/patients/{created['id']}", json={"first_name": "AMINA"})
    assert response.status_code == 200


def test_put_is_not_supported(client, patient_payload):
    created = create(client, **patient_payload())
    assert client.put(f"/api/patients/{created['id']}", json=patient_payload()).status_code == 405


# --- deactivate / reactivate / no delete -------------------------------------


def test_deactivate_patient(client, patient_payload):
    created = create(client, **patient_payload())
    response = client.post(
        f"/api/patients/{created['id']}/deactivate", json={"reason": "  Deceased - confirmed  "}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INACTIVE"
    assert body["deactivation_reason"] == "Deceased - confirmed"
    assert body["deactivated_at"] is not None
    # Still retrievable: deactivation is not deletion.
    assert client.get(f"/api/patients/{created['id']}").json()["status"] == "INACTIVE"


def test_deactivate_requires_reason(client, patient_payload):
    created = create(client, **patient_payload())
    assert client.post(f"/api/patients/{created['id']}/deactivate", json={}).status_code == 422
    assert client.post(f"/api/patients/{created['id']}/deactivate", json={"reason": " "}).status_code == 422
    assert client.get(f"/api/patients/{created['id']}").json()["status"] == "ACTIVE"


def test_deactivate_twice_is_409(client, patient_payload):
    created = create(client, **patient_payload())
    client.post(f"/api/patients/{created['id']}/deactivate", json={"reason": "Moved away"})
    response = client.post(f"/api/patients/{created['id']}/deactivate", json={"reason": "Again"})
    assert response.status_code == 409
    assert "already inactive" in response.json()["detail"]


def test_deactivate_missing_patient_is_404(client):
    response = client.post(f"/api/patients/{uuid.uuid4()}/deactivate", json={"reason": "x"})
    assert response.status_code == 404


def test_reactivate_patient(client, patient_payload):
    created = create(client, **patient_payload())
    client.post(f"/api/patients/{created['id']}/deactivate", json={"reason": "Registered in error"})
    response = client.post(f"/api/patients/{created['id']}/reactivate")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ACTIVE"
    assert body["deactivated_at"] is None and body["deactivation_reason"] is None


def test_reactivate_active_patient_is_409(client, patient_payload):
    created = create(client, **patient_payload())
    assert client.post(f"/api/patients/{created['id']}/reactivate").status_code == 409


def test_delete_is_not_allowed_and_record_remains(client, patient_payload):
    created = create(client, **patient_payload())
    assert client.delete(f"/api/patients/{created['id']}").status_code == 405
    assert client.get(f"/api/patients/{created['id']}").status_code == 200
