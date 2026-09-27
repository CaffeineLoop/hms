"""Read-only evidence tools for the AI assistant (Stages 7-8).

Each tool is a LangChain `StructuredTool` that:
- is bound to ONE patient when created (the model cannot choose or change the patient);
- declares the HMS permission the caller must hold to use it (role-aware);
- reads through `AIEvidenceRepository` only (fixed, patient-bound queries; no SQL is exposed and no
  free-form queries). Stage 8: optionally limited to a time window [since, until];
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
from sqlalchemy.orm import Session

from app.core.clock import facility_today
from app.core.permissions import P
from app.repositories.ai_evidence_repository import AIEvidenceRepository

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


# --- tool implementations (pure reads) -----------------------------------------------------------


def _patient_profile(repo: AIEvidenceRepository, patient_id: uuid.UUID, limit: int, since=None, until=None) -> list[Evidence]:
    patient = repo.patient(patient_id)
    return [{"source_id": f"patient:{patient.id}", "type": "patient", "occurred_at": None,
             "data": {"patient_number": patient.patient_number, "age_years": _age(patient.date_of_birth),
                      "sex": patient.sex, "status": patient.status}}]


def _encounters(repo, patient_id, limit, since=None, until=None):
    return [{"source_id": f"encounter:{e.id}", "type": "encounter", "occurred_at": _iso(e.start_at),
             "data": {"encounter_type": e.encounter_type, "status": e.status, "reason": _clip(e.reason, 500),
                      "start_at": _iso(e.start_at), "end_at": _iso(e.end_at), "summary": _clip(e.summary)}}
            for e in repo.encounters(patient_id, limit, since, until)]


def _observations(repo, patient_id, limit, since=None, until=None):
    return [{"source_id": f"observation:{o.id}", "type": "observation", "occurred_at": _iso(o.effective_at),
             "data": {"code": o.code, "display": o.display, "value": o.value_numeric if o.value_numeric is not None
                      else _clip(o.value_text, 300), "unit": o.unit, "effective_at": _iso(o.effective_at)}}
            for o in repo.observations(patient_id, limit, since, until)]


def _conditions(repo, patient_id, limit, since=None, until=None):
    return [{"source_id": f"condition:{c.id}", "type": "condition", "occurred_at": _iso(c.onset_at or c.recorded_at),
             "data": {"name": c.name, "code": c.code, "status": c.status, "onset_at": _iso(c.onset_at),
                      "resolved_at": _iso(c.resolved_at), "recorded_at": _iso(c.recorded_at)}}
            for c in repo.conditions(patient_id, limit, since, until)]


def _allergies(repo, patient_id, limit, since=None, until=None):
    return [{"source_id": f"allergy:{a.id}", "type": "allergy", "occurred_at": _iso(a.recorded_at),
             "data": {"substance": a.substance, "category": a.category, "reaction": _clip(a.reaction, 300),
                      "severity": a.severity, "status": a.status}}
            for a in repo.allergies(patient_id, limit, since, until)]


def _medications(repo, patient_id, limit, since=None, until=None):
    return [{"source_id": f"prescription:{rx.id}", "type": "prescription", "occurred_at": _iso(rx.prescribed_at),
             "data": {"status": rx.status, "prescribed_at": _iso(rx.prescribed_at),
                      "items": [{"medicine": i.medicine_name, "dose": f"{i.dose_value:g} {i.dose_unit}",
                                 "route": i.route, "frequency": i.frequency,
                                 "duration": f"{i.duration_value} {i.duration_unit}" if i.duration_value else None}
                                for i in rx.items]}}
            for rx in repo.medications(patient_id, limit, since, until)]


def _lab_results(repo, patient_id, limit, since=None, until=None):
    results = repo.lab_results(patient_id, limit, since, until)  # released orders only
    return [{"source_id": f"lab_result:{r.id}", "type": "lab_result", "occurred_at": _iso(r.resulted_at),
             "data": {"test": r.lab_order.test_name, "analyte": r.analyte_name,
                      "value": r.value_numeric if r.value_numeric is not None else _clip(r.value_text, 300),
                      "unit": r.unit, "reference_low": r.reference_low, "reference_high": r.reference_high,
                      "reference_text": r.reference_text, "interpretation": r.interpretation,
                      "resulted_at": _iso(r.resulted_at)}}
            for r in results]


def _reports(repo, patient_id, limit, since=None, until=None):
    return [{"source_id": f"report:{r.id}", "type": "report", "occurred_at": _iso(r.effective_at),
             "data": {"report_type": r.report_type, "title": r.title, "conclusion": _clip(r.conclusion, 800),
                      "content": _clip(r.content), "effective_at": _iso(r.effective_at)}}
            for r in repo.reports(patient_id, limit, since, until)]


def _clinical_notes(repo, patient_id, limit, since=None, until=None):
    return [{"source_id": f"clinical_note:{n.id}", "type": "clinical_note", "occurred_at": _iso(n.authored_at),
             "data": {"note_type": n.note_type, "authored_at": _iso(n.authored_at), "content": _clip(n.content)}}
            for n in repo.clinical_notes(patient_id, limit, since, until)]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    permission: P
    read: Callable[..., list[Evidence]]


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


def bind_tools(session: Session, patient_id: uuid.UUID, limit: int, names: list[str], *,
               since: datetime | None = None, until: datetime | None = None) -> list[StructuredTool]:
    """LangChain tools bound to one patient, one (read-only) session and an optional time window.
    They take no arguments, so nothing the model or the user writes can redirect them to another
    patient, another period or another query."""
    repo = AIEvidenceRepository(session)
    tools = []
    for name in names:
        spec = TOOLS_BY_NAME[name]
        tools.append(StructuredTool.from_function(
            func=lambda _spec=spec: _spec.read(repo, patient_id, limit, since, until),
            name=spec.name,
            description=spec.description,
        ))
    return tools
