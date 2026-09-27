"""Stage 10: architectural compatibility check for future Synthea / FHIR R4 ingestion.

NOT an importer. A small invented Synthea-style bundle (tests/fixtures/synthea_sample_bundle.json) is
mapped by a minimal test-only mapper onto the EXISTING HMS API and loaded through the staff-less
principal (the explicit-identity path reserved for a future controlled importer). The test proves
the current clinical schema can hold Synthea's core resources without redesign, and records what
an eventual importer must still handle (UNMAPPED). The controlled import/backfill path remains a
separate implementation concern.
"""

import json
from pathlib import Path

import pytest

from app.core.permissions import DEFAULT_ROLES
from app.services.observation_catalog import CATALOG

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]

BUNDLE = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "synthea_sample_bundle.json")
                    .read_text(encoding="utf-8"))
LOINC = "http://loinc.org"
LOINC_TO_HMS = {definition.loinc: code for code, definition in CATALOG.items()}
ENCOUNTER_CLASS = {"AMB": "OPD", "EMER": "EMERGENCY", "IMP": "INPATIENT"}
FREQUENCY = {(1, 1, "d"): "OD", (2, 1, "d"): "BID", (3, 1, "d"): "TID", (4, 1, "d"): "QID"}

# What the current schema does not store - requirements for the future importer, not defects.
UNMAPPED = {
    "Patient.identifier / every resource id": "no source-identifier column: an idempotent backfill needs a mapping "
                                              "table or external-id column (importer concern)",
    "Encounter.type (SNOMED)": "encounter keeps type (OPD/EMERGENCY/INPATIENT) and free-text reason only",
    "DiagnosticReport.issued / lab verify-release times": "lab verification/release are recorded at import time",
    "MedicationRequest.dosageInstruction (complex timing)": "only timings matching the HMS Frequency enum map",
    "Condition.verificationStatus": "folded into HMS status (provisional -> SUSPECTED)",
    "Chronological consistency": "HMS enforces record times >= linked encounter start; the importer must load "
                                 "encounters first and link only the diagnosing encounter",
}


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json()


def resources(kind: str) -> list[dict]:
    return [e["resource"] for e in BUNDLE["entry"] if e["resource"]["resourceType"] == kind]


def coding(concept: dict) -> dict:
    return concept["coding"][0]


def load_bundle(client) -> dict:
    """Minimal test-only mapping of the bundle onto the HMS API (returns created ids by FHIR id)."""
    ids: dict[str, dict] = {}
    [fp] = resources("Patient")
    name, address = fp["name"][0], fp["address"][0]
    patient = ok(client.post("/api/patients", json={
        "first_name": name["given"][0], "middle_name": name["given"][1], "last_name": name["family"],
        "sex": fp["gender"].upper(), "date_of_birth": fp["birthDate"], "phone": fp["telecom"][0]["value"],
        "address_line1": address["line"][0], "city": address["city"], "state_province": address["state"],
        "postal_code": address["postalCode"], "country": address["country"]}), 201)
    ids[fp["id"]] = patient
    P = f"/api/patients/{patient['id']}"
    for fe in resources("Encounter"):
        ids[fe["id"]] = ok(client.post(f"{P}/encounters", json={
            "encounter_type": ENCOUNTER_CLASS[fe["class"]["code"]], "status": fe["status"].upper(),
            "reason": coding(fe["reasonCode"][0])["display"], "start_at": fe["period"]["start"],
            "end_at": fe["period"]["end"]}), 201)

    def encounter_of(resource):
        reference = resource.get("encounter")  # e.g. a chronic condition diagnosed at an earlier, absent encounter
        return ids[reference["reference"].split("/")[1]]["id"] if reference else None

    lab_results = {r["result"][0]["reference"].split("/")[1] for r in resources("DiagnosticReport")}
    for fo in resources("Observation"):
        if fo["id"] in lab_results:
            continue  # imported through the laboratory workflow below
        parts = fo.get("component") or [fo]
        for part in parts:
            loinc = coding(part["code"])["code"]
            ids.setdefault(fo["id"], []).append(ok(client.post(f"{P}/observations", json={
                "code": LOINC_TO_HMS[loinc], "value_numeric": part["valueQuantity"]["value"],
                "unit": part["valueQuantity"]["code"], "effective_at": fo["effectiveDateTime"],
                "encounter_id": encounter_of(fo)}), 201))
    for fc in resources("Condition"):
        clinical, verification = coding(fc["clinicalStatus"])["code"], coding(fc["verificationStatus"])["code"]
        status = "RESOLVED" if clinical == "resolved" else ("SUSPECTED" if verification == "provisional" else "ACTIVE")
        code = coding(fc["code"])
        ids[fc["id"]] = ok(client.post(f"{P}/conditions", json={
            "name": code["display"], "code_system": code["system"], "code": code["code"], "status": status,
            "onset_at": fc["onsetDateTime"], "resolved_at": fc.get("abatementDateTime"),
            "recorded_at": fc["recordedDate"], "encounter_id": encounter_of(fc)}), 201)
    for fa in resources("AllergyIntolerance"):
        code, reaction = coding(fa["code"]), fa["reaction"][0]
        ids[fa["id"]] = ok(client.post(f"{P}/allergies", json={
            "substance": code["display"], "code_system": code["system"], "code": code["code"],
            "category": fa["category"][0].upper(), "severity": reaction["severity"].upper(),
            "reaction": coding(reaction["manifestation"][0])["display"], "recorded_at": fa["recordedDate"]}), 201)
    for fm in resources("MedicationRequest"):
        med, dosage = coding(fm["medicationCodeableConcept"]), fm["dosageInstruction"][0]
        repeat, dose = dosage["timing"]["repeat"], dosage["doseAndRate"][0]["doseQuantity"]
        rx = ok(client.post(f"{P}/prescriptions", json={
            "encounter_id": encounter_of(fm), "prescriber_name": fm["requester"]["display"],
            "prescribed_at": fm["authoredOn"], "items": [{
                "medicine_name": med["display"], "code_system": med["system"], "code": med["code"],
                "dose_value": dose["value"], "dose_unit": dose["unit"], "route": "ORAL",
                "frequency": FREQUENCY[(repeat["frequency"], repeat["period"], repeat["periodUnit"])]}]}), 201)
        if fm["status"] == "active":
            rx = ok(client.post(f"/api/prescriptions/{rx['id']}/activate"))
        ids[fm["id"]] = rx
    by_id = {r["id"]: r for r in resources("Observation")}
    for fd in resources("DiagnosticReport"):
        code = coding(fd["code"])
        order = ok(client.post(f"{P}/lab-orders", json={
            "encounter_id": encounter_of(fd), "test_code": "cbc_panel", "test_name": code["display"],
            "code_system": code["system"], "system_code": code["code"], "ordered_by": "Synthea import",
            "ordered_at": fd["effectiveDateTime"]}), 201)
        ok(client.post(f"/api/lab-orders/{order['id']}/samples", json={
            "specimen_type": "BLOOD", "collected_by": "Synthea import", "collected_at": fd["effectiveDateTime"]}), 201)
        ok(client.post(f"/api/lab-orders/{order['id']}/start-processing"))
        results = []
        for ref in fd["result"]:
            fo = by_id[ref["reference"].split("/")[1]]
            obs_code, rng = coding(fo["code"]), fo["referenceRange"][0]
            results.append({"analyte_code": "hemoglobin", "analyte_name": obs_code["display"],
                            "code_system": obs_code["system"], "system_code": obs_code["code"],
                            "value_numeric": fo["valueQuantity"]["value"], "unit": fo["valueQuantity"]["code"],
                            "reference_low": rng["low"]["value"], "reference_high": rng["high"]["value"],
                            "interpretation": {"L": "LOW", "H": "HIGH", "N": "NORMAL"}[
                                coding(fo["interpretation"][0])["code"]],
                            "resulted_at": fo["effectiveDateTime"]})
        ok(client.post(f"/api/lab-orders/{order['id']}/results", json={"entered_by": "Synthea import",
                                                                        "results": results}))
        ok(client.post(f"/api/lab-orders/{order['id']}/verify", json={"verified_by": "Synthea import"}))
        ids[fd["id"]] = ok(client.post(f"/api/lab-orders/{order['id']}/release"))
    return ids


def test_catalog_uses_the_loinc_codes_synthea_exports():
    for code in ("8310-5", "8867-4", "8480-6", "8462-4", "29463-7", "2339-0"):
        assert code in LOINC_TO_HMS, code
    for definition in CATALOG.values():
        assert definition.units and all(unit.strip() for unit in definition.units)  # UCUM strings


def test_synthea_style_bundle_fits_the_existing_schema(client, auth_client, make_user):
    ids = load_bundle(client)
    patient = ids["p-7f3c"]
    assert patient["phone"] == "+254700555111" and patient["middle_name"] == "Njeri"
    temp, = ids["o-temp"]
    assert temp["code"] == "body_temperature" and temp["system_code"] == "8310-5" and temp["code_system"] == LOINC
    systolic, diastolic = ids["o-bp"]
    assert (systolic["code"], diastolic["code"]) == ("systolic_blood_pressure", "diastolic_blood_pressure")
    assert systolic["effective_at"] == diastolic["effective_at"]  # the BP panel shape Synthea exports
    assert ids["c-dm"]["code"] == "44054006" and ids["c-dm"]["status"] == "ACTIVE"
    assert ids["c-fever"]["status"] == "RESOLVED" and ids["c-fever"]["resolved_at"]
    assert ids["a-pen"]["code_system"].endswith("rxnorm") and ids["a-pen"]["severity"] == "MODERATE"
    assert ids["m-metformin"]["status"] == "ACTIVE" and ids["m-metformin"]["items"][0]["code"] == "860975"
    lab = ids["dr-cbc"]
    assert lab["status"] == "RELEASED" and lab["results"][0]["interpretation"] == "LOW"

    timeline = ok(client.get(f"/api/patients/{patient['id']}/timeline", params={"limit": 100}))
    assert {"encounter", "observation", "condition", "allergy", "prescription", "lab_order"} <= {
        e["event_type"] for e in timeline["items"]}

    # Imported history is usable by the AI through the same read-only, permission-checked path
    # (retrospective reference time inside the imported encounter; horizon still exactly 4 days).
    grants = [{"code": c.value, "scope": s.value} for c, s in DEFAULT_ROLES["DOCTOR"][1].items()]
    ok(client.post("/api/roles", json={"name": "SYN_DOCTOR", "permissions": grants + [{"code": "ai.analysis"}]}), 201)
    doctor = make_user("SYN_DOCTOR")
    body = ok(auth_client.post("/api/ai/analyses", headers=doctor["headers"], json={
        "patient_id": patient["id"], "analysis_type": "FOUR_DAY_RISK", "reference_at": "2025-11-03T11:00:00Z"}))
    assert body["status"] == "COMPLETED" and body["risk"]["horizon_end"].startswith("2025-11-07T11:00:00")
    rules = {s["rule_id"] for s in body["risk"]["signals"]}
    assert "demo-v1.vital_high.body_temperature" in rules and any(r.startswith("demo-v1.lab_abnormal") for r in rules)
    assert "Wanjala" not in json.dumps(body) and "Rehema" not in json.dumps(body)


def test_unmapped_fields_are_documented():
    """Keeps the importer requirements explicit (see the Stage 10 report)."""
    assert len(UNMAPPED) == 6 and all(reason for reason in UNMAPPED.values())
