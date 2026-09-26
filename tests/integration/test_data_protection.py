"""Stage 6 data protection: no credential/secret/patient-data leakage in responses and logs."""

import logging

import pytest

from app.core import security

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]

FORBIDDEN_KEYS = {"password", "password_hash", "token_hash", "hash", "secret"}


def keys(obj) -> set[str]:
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in keys(v)}
    return set()


def test_account_endpoints_never_expose_credentials(auth_client, make_user):
    admin, doctor = make_user("SUPER_ADMIN"), make_user("DOCTOR")
    responses = [
        auth_client.post("/api/auth/login", json={"username": doctor["user"]["username"], "password": doctor["password"]}),
        auth_client.get("/api/auth/me", headers=doctor["headers"]),
        auth_client.get("/api/users", headers=admin["headers"]),
        auth_client.get(f"/api/users/{doctor['user']['id']}", headers=admin["headers"]),
        auth_client.get("/api/audit-events", params={"limit": 100}, headers=admin["headers"]),
    ]
    for response in responses:
        assert response.status_code == 200, response.text
        assert not keys(response.json()) & FORBIDDEN_KEYS
        assert "scrypt$" not in response.text and doctor["password"] not in response.text
        assert security.token_digest(doctor["token"]) not in response.text
    # The only response that ever contains a token is the login that created it.
    assert doctor["token"] not in "".join(r.text for r in responses)


def test_patient_search_terms_do_not_reach_application_logs(auth_client, make_user, caplog):
    doctor = make_user("DOCTOR")
    with caplog.at_level(logging.DEBUG):
        auth_client.post("/api/patients", headers=doctor["headers"], json={
            "first_name": "Zenobia", "last_name": "Quartermaine", "date_of_birth": "1975-05-05", "sex": "FEMALE",
            "phone": "+254700999888"})
        auth_client.get("/api/patients", params={"q": "Quartermaine"}, headers=doctor["headers"])
        auth_client.post("/api/patients", headers=doctor["headers"], json={  # duplicate -> 409 path
            "first_name": "Zenobia", "last_name": "Quartermaine", "date_of_birth": "1975-05-05", "sex": "FEMALE",
            "phone": "+254700999888"})
    # Only server-side loggers count: the test's own HTTP client (httpx2) logs request URLs itself.
    server_logs = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    assert "Quartermaine" not in server_logs and "+254700999888" not in server_logs


def test_integrity_errors_do_not_leak_sql(client, monkeypatch, patient_payload):
    """Force the database backstop: the response names no table, column, value or SQL."""
    from app.repositories.patient_repository import PatientRepository

    body = patient_payload(phone="0712345678")
    assert client.post("/api/patients", json=body).status_code == 201
    monkeypatch.setattr(PatientRepository, "find_duplicates", lambda self, **kw: [])
    response = client.post("/api/patients", json=body)
    assert response.status_code == 409
    for fragment in ("INSERT", "patients", "psycopg", "0712345678", "DETAIL", "uq_"):
        assert fragment not in response.text


def test_forbidden_responses_do_not_reveal_record_contents(auth_client, make_user, client, patient_payload):
    patient = client.post("/api/patients", json=patient_payload(first_name="Hidden")).json()
    pharmacist = make_user("PHARMACIST")
    response = auth_client.get(f"/api/patients/{patient['id']}/clinical-notes", headers=pharmacist["headers"])
    assert response.status_code == 403 and "Hidden" not in response.text
    assert response.json() == {"detail": "Missing permission: clinical_note.view."}
