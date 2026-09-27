"""Read-only evidence queries for the AI assistant (Stages 7-8).

Stage 8 correction of a Stage 7 layering gap: the AI tools previously issued SQLAlchemy selects
directly; they now go through this repository (Router -> Service -> Repository -> SQLAlchemy).
Queries are fixed and patient-bound, optionally limited to a time window [since, until].
The session passed in is the graph's READ ONLY transaction; there are no write methods.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.allergy import Allergy
from app.models.clinical_note import ClinicalNote
from app.models.condition import Condition
from app.models.encounter import Encounter
from app.models.laboratory import LabOrder, LabOrderStatus, LabResult
from app.models.observation import Observation
from app.models.patient import Patient
from app.models.prescription import Prescription, PrescriptionStatus
from app.models.report import Report, ReportStatus


class AIEvidenceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _latest(self, model, patient_id: uuid.UUID, time_column, limit: int, since: datetime | None,
                until: datetime | None, *where) -> list:
        statement = select(model).where(model.patient_id == patient_id, *where)
        if since is not None:
            statement = statement.where(time_column >= since)
        if until is not None:
            statement = statement.where(time_column <= until)
        return list(self._session.execute(statement.order_by(time_column.desc(), model.id).limit(limit)).scalars())

    def patient(self, patient_id: uuid.UUID) -> Patient | None:
        return self._session.get(Patient, patient_id)

    def encounters(self, patient_id, limit, since=None, until=None) -> list[Encounter]:
        # An encounter that started before the window may still be ongoing: only `until` applies.
        return self._latest(Encounter, patient_id, Encounter.start_at, limit, None, until)

    def observations(self, patient_id, limit, since=None, until=None) -> list[Observation]:
        return self._latest(Observation, patient_id, Observation.effective_at, limit, since, until)

    def conditions(self, patient_id, limit, since=None, until=None) -> list[Condition]:
        # Conditions, allergies and medications describe current state: only `until` applies.
        return self._latest(Condition, patient_id, Condition.recorded_at, limit, None, until)

    def allergies(self, patient_id, limit, since=None, until=None) -> list[Allergy]:
        return self._latest(Allergy, patient_id, Allergy.recorded_at, limit, None, until)

    def medications(self, patient_id, limit, since=None, until=None) -> list[Prescription]:
        issued = Prescription.status != PrescriptionStatus.DRAFT.value  # drafts are not prescriptions yet
        return self._latest(Prescription, patient_id, Prescription.prescribed_at, limit, None, until, issued)

    def lab_results(self, patient_id, limit, since=None, until=None) -> list[LabResult]:
        released = LabResult.lab_order_id.in_(
            select(LabOrder.id).where(LabOrder.status == LabOrderStatus.RELEASED.value))
        return self._latest(LabResult, patient_id, LabResult.resulted_at, limit, since, until, released)

    def reports(self, patient_id, limit, since=None, until=None) -> list[Report]:
        released = Report.status == ReportStatus.RELEASED.value
        return self._latest(Report, patient_id, Report.effective_at, limit, since, until, released)

    def clinical_notes(self, patient_id, limit, since=None, until=None) -> list[ClinicalNote]:
        return self._latest(ClinicalNote, patient_id, ClinicalNote.authored_at, limit, since, until)
