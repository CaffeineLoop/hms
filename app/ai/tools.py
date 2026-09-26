"""Read-only evidence tools for the AI assistant (Stage 7).

Each tool is a LangChain `StructuredTool` that:
- is bound to ONE patient when created (the model cannot choose or change the patient);
- declares the HMS permission the caller must hold to use it (role-aware);
- reads through the existing repositories only (no SQL is exposed, no free-form queries);
- returns minimized evidence items: {"source_id", "type", "occurred_at", "data"}.

There are no write tools. `ALLOWED_TOOL_NAMES` is the complete allowlist, and the graph runs the
tools inside a `SET TRANSACTION READ ONLY` session, so even a coding mistake cannot write.

Data minimization: the patient's name, phone, email and address are never included; the
profile carries only the Patient ID, age and sex. Free text is truncated.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from langchain_core.tools import StructuredTool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import facility_today
from app.core.permissions import P
from app.models.allergy import Allergy
from app.models.clinical_note import ClinicalNote
from app.models.condition import Condition
from app.models.encounter import Encounter
from app.models.laboratory import LabOrder, LabOrderStatus, LabResult
from app.models.observation import Observation
from app.models.patient import Patient
from app.models.prescription import Prescription, PrescriptionStatus
from app.models.report import Report, ReportStatus

Evidence = dict[str, Any]
TEXT_LIMIT = 1500


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _clip(value: str | None, limit: int = TEXT_LIMIT) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[:limit] + " [truncated]"


def _age(dob: date) -> int:
    today = facility_today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _latest(session: Session, model, patient_id: uuid.UUID, time_column, limit: int, *where):
    statement = (select(model).where(model.patient_id == patient_id, *where)
                 .order_by(time_column.desc(), model.id).limit(limit))
    return list(session.execute(statement).scalars())


# --- tool implementations (pure reads) -----------------------------------------------------------


def _patient_profile(session: Session, patient_id: uuid.UUID, limit: int) -> list[Evidence]:
    patient = session.get(Patient, patient_id)
    return [{"source_id": f"patient:{patient.id}", "type": "patient", "occurred_at": None,
             "data": {"patient_number": patient.patient_number, "age_years": _age(patient.date_of_birth),
                      "sex": patient.sex, "status": patient.status}}]


def _encounters(session, patient_id, limit):
    return [{"source_id": f"encounter:{e.id}", "type": "encounter", "occurred_at": _iso(e.start_at),
             "data": {"encounter_type": e.encounter_type, "status": e.status, "reason": _clip(e.reason, 500),
                      "start_at": _iso(e.start_at), "end_at": _iso(e.end_at), "summary": _clip(e.summary)}}
            for e in _latest(session, Encounter, patient_id, Encounter.start_at, limit)]


def _observations(session, patient_id, limit):
    return [{"source_id": f"observation:{o.id}", "type": "observation", "occurred_at": _iso(o.effective_at),
             "data": {"code": o.code, "display": o.display, "value": o.value_numeric if o.value_numeric is not None
                      else _clip(o.value_text, 300), "unit": o.unit, "effective_at": _iso(o.effective_at)}}
            for o in _latest(session, Observation, patient_id, Observation.effective_at, limit)]


def _conditions(session, patient_id, limit):
    return [{"source_id": f"condition:{c.id}", "type": "condition", "occurred_at": _iso(c.onset_at or c.recorded_at),
             "data": {"name": c.name, "code": c.code, "status": c.status, "onset_at": _iso(c.onset_at),
                      "resolved_at": _iso(c.resolved_at), "recorded_at": _iso(c.recorded_at)}}
            for c in _latest(session, Condition, patient_id, Condition.recorded_at, limit)]


def _allergies(session, patient_id, limit):
    return [{"source_id": f"allergy:{a.id}", "type": "allergy", "occurred_at": _iso(a.recorded_at),
             "data": {"substance": a.substance, "category": a.category, "reaction": _clip(a.reaction, 300),
                      "severity": a.severity, "status": a.status}}
            for a in _latest(session, Allergy, patient_id, Allergy.recorded_at, limit)]


def _medications(session, patient_id, limit):
    issued = Prescription.status != PrescriptionStatus.DRAFT.value  # drafts are not prescriptions yet
    return [{"source_id": f"prescription:{rx.id}", "type": "prescription", "occurred_at": _iso(rx.prescribed_at),
             "data": {"status": rx.status, "prescribed_at": _iso(rx.prescribed_at),
                      "items": [{"medicine": i.medicine_name, "dose": f"{i.dose_value:g} {i.dose_unit}",
                                 "route": i.route, "frequency": i.frequency,
                                 "duration": f"{i.duration_value} {i.duration_unit}" if i.duration_value else None}
                                for i in rx.items]}}
            for rx in _latest(session, Prescription, patient_id, Prescription.prescribed_at, limit, issued)]


def _lab_results(session, patient_id, limit):
    released = LabResult.lab_order_id.in_(select(LabOrder.id).where(LabOrder.status == LabOrderStatus.RELEASED.value))
    results = _latest(session, LabResult, patient_id, LabResult.resulted_at, limit, released)
    return [{"source_id": f"lab_result:{r.id}", "type": "lab_result", "occurred_at": _iso(r.resulted_at),
             "data": {"test": r.lab_order.test_name, "analyte": r.analyte_name,
                      "value": r.value_numeric if r.value_numeric is not None else _clip(r.value_text, 300),
                      "unit": r.unit, "reference_low": r.reference_low, "reference_high": r.reference_high,
                      "reference_text": r.reference_text, "interpretation": r.interpretation,
                      "resulted_at": _iso(r.resulted_at)}}
            for r in results]


def _reports(session, patient_id, limit):
    released = Report.status == ReportStatus.RELEASED.value
    return [{"source_id": f"report:{r.id}", "type": "report", "occurred_at": _iso(r.effective_at),
             "data": {"report_type": r.report_type, "title": r.title, "conclusion": _clip(r.conclusion, 800),
                      "content": _clip(r.content), "effective_at": _iso(r.effective_at)}}
            for r in _latest(session, Report, patient_id, Report.effective_at, limit, released)]


def _clinical_notes(session, patient_id, limit):
    return [{"source_id": f"clinical_note:{n.id}", "type": "clinical_note", "occurred_at": _iso(n.authored_at),
             "data": {"note_type": n.note_type, "authored_at": _iso(n.authored_at), "content": _clip(n.content)}}
            for n in _latest(session, ClinicalNote, patient_id, ClinicalNote.authored_at, limit)]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    permission: P
    read: Callable[[Session, uuid.UUID, int], list[Evidence]]


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("get_patient_profile", "Patient ID, age, sex and status (no name or contact details).",
             P.PATIENT_VIEW, _patient_profile),
    ToolSpec("get_encounters", "Recent encounters: type, status, reason, dates, summary.", P.ENCOUNTER_VIEW, _encounters),
    ToolSpec("get_observations", "Recent observations and vital signs with units and times.",
             P.OBSERVATION_VIEW, _observations),
    ToolSpec("get_conditions", "Documented conditions with status and dates.", P.CONDITION_VIEW, _conditions),
    ToolSpec("get_allergies", "Documented allergies with reaction and severity.", P.ALLERGY_VIEW, _allergies),
    ToolSpec("get_medications", "Issued prescriptions (not drafts) with dose, route and frequency.",
             P.PRESCRIPTION_VIEW, _medications),
    ToolSpec("get_lab_results", "Released lab results with reference ranges.", P.LAB_VIEW, _lab_results),
    ToolSpec("get_reports", "Released clinical reports.", P.REPORT_VIEW, _reports),
    ToolSpec("get_clinical_notes", "Recent clinical notes (truncated).", P.CLINICAL_NOTE_VIEW, _clinical_notes),
)
TOOLS_BY_NAME = {spec.name: spec for spec in TOOL_SPECS}
ALLOWED_TOOL_NAMES = frozenset(TOOLS_BY_NAME)


def bind_tools(session: Session, patient_id: uuid.UUID, limit: int, names: list[str]) -> list[StructuredTool]:
    """LangChain tools bound to one patient and one (read-only) session. They take no arguments,
    so nothing the model or the user writes can redirect them to another patient or query."""
    tools = []
    for name in names:
        spec = TOOLS_BY_NAME[name]
        tools.append(StructuredTool.from_function(
            func=lambda _spec=spec: _spec.read(session, patient_id, limit),
            name=spec.name,
            description=spec.description,
        ))
    return tools
