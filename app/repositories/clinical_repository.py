"""Data access for clinical records (Stages 2-3). No business rules and no commits."""

import uuid
from typing import Any, ClassVar

from sqlalchemy import Sequence, func, select
from sqlalchemy.orm import Session

from app.models.allergy import Allergy
from app.models.clinical_note import ClinicalNote
from app.models.condition import Condition
from app.models.encounter import Encounter
from app.models.laboratory import LabOrder, LabResult, LabSample
from app.models.observation import Observation
from app.models.prescription import Prescription, PrescriptionItem
from app.models.report import Report


class ClinicalRecordRepository[M]:
    """Generic get/add/list for a clinical-record table.

    Lists are ordered by the record's clinical time (newest first), then by system
    `created_at`, then by `id`, so the order is fully deterministic.
    """

    model: ClassVar[type]
    clinical_time: ClassVar[str]  # name of the column holding the clinical timestamp

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, record_id: uuid.UUID, *, for_update: bool = False) -> M | None:
        statement = select(self.model).where(self.model.id == record_id)
        if for_update:
            statement = statement.with_for_update()
        return self._session.execute(statement).scalar_one_or_none()

    def add(self, record: M) -> M:
        self._session.add(record)
        self._session.flush()
        return record

    def list_for_patient(
        self, patient_id: uuid.UUID, *, filters: dict[str, Any], limit: int, offset: int
    ) -> tuple[list[M], int]:
        conditions = [self.model.patient_id == patient_id]
        conditions += [getattr(self.model, name) == value for name, value in filters.items() if value is not None]
        total = self._session.execute(
            select(func.count()).select_from(self.model).where(*conditions)
        ).scalar_one()
        items = self._session.execute(
            select(self.model)
            .where(*conditions)
            .order_by(getattr(self.model, self.clinical_time).desc(), self.model.created_at.desc(), self.model.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return list(items), total


class EncounterRepository(ClinicalRecordRepository[Encounter]):
    model = Encounter
    clinical_time = "start_at"


class ObservationRepository(ClinicalRecordRepository[Observation]):
    model = Observation
    clinical_time = "effective_at"


class ConditionRepository(ClinicalRecordRepository[Condition]):
    model = Condition
    clinical_time = "recorded_at"


class AllergyRepository(ClinicalRecordRepository[Allergy]):
    model = Allergy
    clinical_time = "recorded_at"

    def active_for_substance(
        self, patient_id: uuid.UUID, substance: str, *, exclude_id: uuid.UUID | None = None
    ) -> Allergy | None:
        statement = select(Allergy).where(
            Allergy.patient_id == patient_id,
            func.lower(Allergy.substance) == substance.lower(),
            Allergy.status == "ACTIVE",
        )
        if exclude_id is not None:
            statement = statement.where(Allergy.id != exclude_id)
        return self._session.execute(statement).scalar_one_or_none()


class ClinicalNoteRepository(ClinicalRecordRepository[ClinicalNote]):
    model = ClinicalNote
    clinical_time = "authored_at"


# --- Stage 3: laboratory, reports, prescriptions -------------------------------------


class SequenceRepository:
    """Draws values for human-facing identifiers (never reused; gaps are possible)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def next_value(self, sequence: Sequence) -> int:
        return self._session.execute(select(sequence.next_value())).scalar_one()


class LabOrderRepository(ClinicalRecordRepository[LabOrder]):
    model = LabOrder
    clinical_time = "ordered_at"


class LabSampleRepository(ClinicalRecordRepository[LabSample]):
    model = LabSample
    clinical_time = "collected_at"


class LabResultRepository(ClinicalRecordRepository[LabResult]):
    model = LabResult
    clinical_time = "resulted_at"


class ReportRepository(ClinicalRecordRepository[Report]):
    model = Report
    clinical_time = "effective_at"


class PrescriptionRepository(ClinicalRecordRepository[Prescription]):
    model = Prescription
    clinical_time = "prescribed_at"

    def add_item(self, item: PrescriptionItem) -> PrescriptionItem:
        self._session.add(item)
        self._session.flush()
        return item
