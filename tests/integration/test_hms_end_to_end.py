"""Stage 10: final end-to-end HMS workflow on hms_test, with real users, tokens and roles.

One realistic encounter crosses every module through the public API, each step performed by the
role that owns it, with restricted operations attempted by the wrong role:

    login -> patient -> encounter -> vitals -> condition/allergy/note -> lab order -> sample ->
    processing -> results -> verify -> release -> report -> prescription -> workflow task ->
    timeline -> AI four-day risk analysis -> human review -> audit trail
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.permissions import DEFAULT_ROLES

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json()


def ago(minutes: float) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()


def role(client, name, *codes, base=None):
    grants = [{"code": c.value, "scope": s.value} for c, s in DEFAULT_ROLES[base][1].items()] if base else []
    ok(client.post("/api/roles", json={"name": name, "permissions": grants + [{"code": c} for c in codes]}), 201)


@pytest.fixture
def team(client, make_user):
    """One user per job, each holding only its role's permissions (plus the explicitly granted AI rights)."""
    role(client, "E2E_DOCTOR", "ai.analysis", base="DOCTOR")
    role(client, "E2E_LAB_SUPERVISOR", "lab.verify", "lab.view", "patient.view")
    role(client, "E2E_AI_REVIEWER", "ai.review", "patient.view")
    role(client, "E2E_AUDITOR", "audit.view")
    return {
        "reception": make_user("RECEPTIONIST"),
        "doctor": make_user("E2E_DOCTOR"),
        "nurse": make_user("NURSE"),
        "lab": make_user("LAB_TECHNICIAN"),
        "supervisor": make_user("E2E_LAB_SUPERVISOR"),
        "pharmacist": make_user("PHARMACIST"),
        "reviewer": make_user("E2E_AI_REVIEWER"),
        "auditor": make_user("E2E_AUDITOR"),
    }


def test_complete_hms_workflow(auth_client, team, test_engine):
    def as_(who):
        headers = team[who]["headers"]

        class Caller:
            def get(self, path, **kw):
                return auth_client.get(path, headers=headers, **kw)

            def post(self, path, body=None):
                return auth_client.post(path, headers=headers, json=body)

        return Caller()

    reception, doctor, nurse, lab = as_("reception"), as_("doctor"), as_("nurse"), as_("lab")
    supervisor, pharmacist, reviewer, auditor = as_("supervisor"), as_("pharmacist"), as_("reviewer"), as_("auditor")

    # 1-2. authenticated login already happened (make_user); unauthenticated access is refused
    assert auth_client.get("/api/patients").status_code == 401
    assert ok(auth_client.get("/api/auth/me", headers=team["doctor"]["headers"]))["username"]

    # 3. reception registers and finds the patient; clinical roles cannot register... except those allowed
    patient = ok(reception.post("/api/patients", {"first_name": "Amina", "last_name": "Otieno", "sex": "FEMALE",
                                                  "date_of_birth": "1968-04-12", "phone": "+254712345678"}), 201)
    found = ok(reception.get("/api/patients", params={"q": "Otieno"}))
    assert [p["id"] for p in found["items"]] == [patient["id"]]
    assert lab.post("/api/patients", {"first_name": "X", "last_name": "Y", "sex": "MALE",
                                      "date_of_birth": "1990-01-01"}).status_code == 403
    P = f"/api/patients/{patient['id']}"

    # 4. doctor opens the encounter; reception may not
    assert reception.post(f"{P}/encounters", {"encounter_type": "OPD", "reason": "x"}).status_code == 403
    encounter = ok(doctor.post(f"{P}/encounters", {"encounter_type": "OPD", "reason": "Fever and cough",
                                                   "start_at": ago(240)}), 201)

    # 5. nurse records vitals; reception may not
    def vital(code, value, unit, minutes):
        return ok(nurse.post(f"{P}/observations", {"code": code, "value_numeric": value, "unit": unit,
                                                   "effective_at": ago(minutes), "encounter_id": encounter["id"]}), 201)

    assert reception.post(f"{P}/observations", {"code": "heart_rate", "value_numeric": 80, "unit": "/min",
                                                "effective_at": ago(1)}).status_code == 403
    vitals = [vital("heart_rate", v, "/min", m) for v, m in ((88, 200), (101, 120), (114, 30))]
    vitals += [vital("body_temperature", 38.8, "Cel", 30), vital("oxygen_saturation", 95, "%", 30)]
    assert all(v["recorded_by_staff_id"] == team["nurse"]["staff"]["id"] for v in vitals if "recorded_by_staff_id" in v)

    # 6. condition, allergy, clinical note (authorship bound to the caller; impersonation refused)
    condition = ok(doctor.post(f"{P}/conditions", {"name": "Malaria", "status": "SUSPECTED"}), 201)
    allergy = ok(nurse.post(f"{P}/allergies", {"substance": "Sulfonamides", "severity": "MODERATE"}), 201)
    note = ok(doctor.post(f"{P}/clinical-notes", {"encounter_id": encounter["id"], "note_type": "PROGRESS",
                                                  "content": "Febrile, tachycardic, mild cough. Malaria suspected."}), 201)
    assert note["author_staff_id"] == team["doctor"]["staff"]["id"]
    assert doctor.post(f"{P}/clinical-notes", {"encounter_id": encounter["id"], "note_type": "PROGRESS",
                                               "content": "x", "author_name": "Someone Else"}).status_code == 403
    assert pharmacist.post(f"{P}/conditions", {"name": "x"}).status_code == 403

    # 7-8. laboratory: order (doctor) -> sample (nurse) -> processing + results (lab) -> verify + release (supervisor)
    assert nurse.post(f"{P}/lab-orders", {"encounter_id": encounter["id"], "test_code": "malaria_rdt",
                                          "test_name": "Malaria RDT"}).status_code == 403
    order = ok(doctor.post(f"{P}/lab-orders", {"encounter_id": encounter["id"], "test_code": "full_blood_count",
                                               "test_name": "Full blood count", "priority": "URGENT",
                                               "clinical_indication": "Fever", "ordered_at": ago(100)}), 201)
    ok(nurse.post(f"/api/lab-orders/{order['id']}/samples", {"specimen_type": "BLOOD", "collected_at": ago(90)}), 201)
    ok(lab.post(f"/api/lab-orders/{order['id']}/start-processing"))
    ok(lab.post(f"/api/lab-orders/{order['id']}/results", {"results": [
        {"analyte_code": "hemoglobin", "analyte_name": "Hemoglobin", "value_numeric": 9.1, "unit": "g/dL",
         "reference_low": 12, "reference_high": 16, "interpretation": "LOW", "resulted_at": ago(60)},
        {"analyte_code": "platelets", "analyte_name": "Platelets", "value_numeric": 98, "unit": "10*3/uL",
         "reference_low": 150, "reference_high": 400, "interpretation": "LOW", "resulted_at": ago(60)}]}))
    assert doctor.post(f"/api/lab-orders/{order['id']}/verify", {}).status_code == 403  # no lab.verify
    assert lab.post(f"/api/lab-orders/{order['id']}/release").status_code == 403
    ok(supervisor.post(f"/api/lab-orders/{order['id']}/verify", {}))
    released = ok(supervisor.post(f"/api/lab-orders/{order['id']}/release"))
    assert released["status"] == "RELEASED" and released["verified_by_staff_id"] == team["supervisor"]["staff"]["id"]

    # 9. report: lab technician authors, doctor verifies and releases
    report = ok(lab.post(f"{P}/reports", {"report_type": "LABORATORY", "title": "FBC report", "lab_order_id": order["id"],
                                          "encounter_id": encounter["id"], "effective_at": ago(55),
                                          "content": "Low haemoglobin and platelets.", "conclusion": "Anaemia, thrombocytopenia."}), 201)
    assert lab.post(f"/api/reports/{report['id']}/verify", {}).status_code == 403
    ok(doctor.post(f"/api/reports/{report['id']}/verify", {}))
    assert ok(doctor.post(f"/api/reports/{report['id']}/release"))["status"] == "RELEASED"

    # 10. prescription: doctor prescribes and activates; pharmacist may hold, but not prescribe
    rx_body = {"encounter_id": encounter["id"], "prescribed_at": ago(20), "items": [{
        "medicine_name": "Artemether-lumefantrine 20/120 mg tablet", "dose_value": 4, "dose_unit": "tablet",
        "route": "ORAL", "frequency": "BID", "duration_value": 3, "duration_unit": "DAYS"}]}
    assert pharmacist.post(f"{P}/prescriptions", rx_body).status_code == 403
    rx = ok(doctor.post(f"{P}/prescriptions", rx_body), 201)
    assert rx["prescriber_staff_id"] == team["doctor"]["staff"]["id"]
    ok(doctor.post(f"/api/prescriptions/{rx['id']}/activate"))
    held = ok(pharmacist.post(f"/api/prescriptions/{rx['id']}/hold", {"reason": "Awaiting stock confirmation"}))
    assert held["status"] == "ON_HOLD"
    assert ok(pharmacist.post(f"/api/prescriptions/{rx['id']}/resume"))["status"] == "ACTIVE"

    # 11. workflow task: doctor assigns to the nurse; nurse (OWN scope) starts and completes it
    task = ok(doctor.post("/api/workflow-tasks", {"workflow_type": "NURSING_CARE", "title": "Repeat vitals in 1 hour",
                                                  "patient_id": patient["id"],
                                                  "assigned_staff_id": team["nurse"]["staff"]["id"]}), 201)
    ok(nurse.post(f"/api/workflow-tasks/{task['id']}/start"))
    done = ok(nurse.post(f"/api/workflow-tasks/{task['id']}/complete", {"completion_notes": "Vitals repeated"}))
    assert done["status"] == "COMPLETED"
    assert reception.post("/api/workflow-tasks", {"workflow_type": "OTHER", "title": "x"}).status_code == 403

    # 12. timeline shows the history from every module
    timeline = ok(doctor.get(f"{P}/timeline", params={"limit": 100}))
    types = {e["event_type"] for e in timeline["items"]}
    assert {"encounter", "observation", "condition", "allergy", "clinical_note", "lab_order", "report",
            "prescription"} <= types, types
    assert reception.get(f"{P}/timeline").status_code == 403

    # 13-15. AI: nurse (no ai.analysis) refused; doctor gets a grounded four-day risk analysis
    assert nurse.post("/api/ai/analyses", {"patient_id": patient["id"], "analysis_type": "FOUR_DAY_RISK"}).status_code == 403
    with test_engine.connect() as c:
        before = {t: c.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
                  for t in ("observations", "conditions", "clinical_notes", "prescriptions", "lab_orders", "workflow_tasks")}
    ai = ok(doctor.post("/api/ai/analyses", {"patient_id": patient["id"], "analysis_type": "FOUR_DAY_RISK"}))
    assert ai["status"] == "COMPLETED", ai
    risk = ai["risk"]
    assert risk["analysis_horizon_days"] == 4 and ai["output"]["analysis_horizon_days"] == 4
    assert datetime.fromisoformat(risk["horizon_end"]) - datetime.fromisoformat(risk["reference_at"]) == timedelta(days=4)
    assert risk["engine"]["validated"] is False and ai["output"]["requires_human_review"] is True
    categories = {s["category"] for s in risk["signals"]}
    assert {"VITAL_SIGN", "VITAL_TREND", "LAB_RESULT"} <= categories, categories
    record_ids = {f"observation:{v['id']}" for v in vitals} | {
        f"lab_result:{r['id']}" for r in released["results"]}
    assert all(set(s["evidence"]) <= record_ids for s in risk["signals"])
    assert set(ai["tools_used"]) == {"get_patient_profile", "get_encounters", "get_observations", "get_conditions",
                                     "get_allergies", "get_medications", "get_lab_results", "get_reports",
                                     "get_clinical_notes"}
    assert "Amina" not in json.dumps(ai) and "Otieno" not in json.dumps(ai) and "+254712345678" not in json.dumps(ai)
    with test_engine.connect() as c:
        after = {t: c.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in before}
    assert after == before  # the AI wrote nothing clinical

    # 16. human review of the AI result (doctor cannot approve their own AI output)
    analysis_id = risk["risk_analysis_id"]
    assert doctor.post(f"/api/ai/risk-analyses/{analysis_id}/review", {"decision": "ACKNOWLEDGED"}).status_code == 403
    reviewed = ok(reviewer.post(f"/api/ai/risk-analyses/{analysis_id}/review",
                                {"decision": "ACKNOWLEDGED", "comment": "Seen with the team."}))
    assert reviewed["review_status"] == "ACKNOWLEDGED" and reviewed["reviewed_by_staff_id"] == team["reviewer"]["staff"]["id"]

    # 17. audit trail: important actions by the right people, readable only with audit.view
    assert doctor.get("/api/audit-events").status_code == 403
    uid = {k: v["user"]["id"] for k, v in team.items()}
    events = ok(auditor.get("/api/audit-events", params={"patient_id": patient["id"], "limit": 100}))["items"]
    # Record-level routes (e.g. /api/lab-orders/{id}/release) are attributed to their resource, not the patient
    # (Stage 6 design); they are found through the actor / resource filters.
    for user_id in uid.values():
        events += ok(auditor.get("/api/audit-events", params={"actor_user_id": user_id, "limit": 100}))["items"]
    release = ok(auditor.get("/api/audit-events", params={"resource_type": "lab-orders", "resource_id": order["id"],
                                                          "limit": 100}))["items"]
    assert any(e["action"] == "POST /api/lab-orders/{order_id}/release" for e in release)
    by_action = {}
    for e in events:
        by_action.setdefault(e["action"], set()).add(e["actor_user_id"])
    expected = {
        "POST /api/patients/{patient_id}/encounters": "doctor",
        "POST /api/patients/{patient_id}/observations": "nurse",
        "POST /api/lab-orders/{order_id}/release": "supervisor",
        "POST /api/prescriptions/{prescription_id}/activate": "doctor",
        "ai.analysis": "doctor",
        "ai.risk_review": "reviewer",
    }
    for action, who in expected.items():
        assert uid[who] in by_action.get(action, set()), (action, sorted(by_action))
    denied = [e for e in events if e["outcome"] == "DENIED"]
    assert denied, "403s on patient routes are audited"
    dump = json.dumps(events)
    assert "Amina" not in dump and "+254712345678" not in dump and "Seen with the team" not in dump
    with test_engine.connect() as c:
        logins = c.execute(text("SELECT count(*) FROM audit_events WHERE action = 'auth.login' AND outcome = 'SUCCESS' "
                                "AND actor_user_id = ANY(:ids)"), {"ids": list(uid.values())}).scalar_one()
    assert logins == len(uid)


def test_no_student_or_research_surface_is_exposed(client):
    """HMS is the source of truth; the Student Clinical Case Portal is a separate downstream system."""
    paths = " ".join(client.get("/openapi.json").json()["paths"]).lower()
    for word in ("student", "research", "deidentif", "de-identif", "anonymi", "export", "eligib", "sync", "case-portal"):
        assert word not in paths, word
