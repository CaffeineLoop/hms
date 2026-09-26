"""Observations, conditions, allergies and clinical notes.

All four share the same creation rules (see clinical_common.py). Conditions and
allergies additionally have controlled status changes; observations and notes are
append-only (a correction is a new record).
"""

import uuid

from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.errors import BusinessValidationError, ConflictError, NotFoundError
from app.models.allergy import ALLERGY_TRANSITIONS, Allergy, AllergyStatus
from app.models.clinical_note import ClinicalNote
from app.models.condition import CONDITION_TRANSITIONS, Condition, ConditionStatus
from app.models.observation import Observation
from app.repositories.clinical_repository import (
    AllergyRepository,
    ClinicalNoteRepository,
    ClinicalRecordRepository,
    ConditionRepository,
    ObservationRepository,
)
from app.schemas.clinical import (
    AllergyCreate,
    AllergyListParams,
    AllergyUpdate,
    ClinicalNoteCreate,
    ClinicalNoteListParams,
    ConditionCreate,
    ConditionListParams,
    ConditionUpdate,
    ObservationCreate,
    ObservationListParams,
)
from app.services.clinical_common import (
    ClinicalContext,
    check_not_before_birth,
    check_not_before_encounter,
    ensure_transition,
)
from app.services.staff_directory import StaffDirectory


class _RecordService[M]:
    label: str
    repository_class: type[ClinicalRecordRepository]

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = self.repository_class(session)
        self._context = ClinicalContext(session)
        self._directory = StaffDirectory(session)

    def get(self, record_id: uuid.UUID) -> M:
        return self._get_or_404(record_id)

    def _list(self, patient_id: uuid.UUID, params, **filters) -> tuple[list[M], int]:
        self._context.patient(patient_id)
        return self._repository.list_for_patient(
            patient_id, filters=filters, limit=params.limit, offset=params.offset
        )

    def _save_new(self, record: M) -> M:
        self._repository.add(record)
        return self._save(record)

    def _save(self, record: M) -> M:
        self._session.commit()
        self._session.refresh(record)
        return record

    def _get_or_404(self, record_id: uuid.UUID, *, for_update: bool = False) -> M:
        record = self._repository.get(record_id, for_update=for_update)
        if record is None:
            raise NotFoundError(f"{self.label} {record_id} not found.")
        return record


class ObservationService(_RecordService[Observation]):
    label = "Observation"
    repository_class = ObservationRepository

    def list_for_patient(self, patient_id: uuid.UUID, params: ObservationListParams):
        return self._list(patient_id, params, code=params.code, encounter_id=params.encounter_id)

    def create(self, patient_id: uuid.UUID, data: ObservationCreate) -> Observation:
        patient = self._context.patient_for_recording(patient_id)
        encounter = self._context.encounter_for_recording(patient, data.encounter_id)
        check_not_before_birth(patient, data.effective_at, "effective_at")
        check_not_before_encounter(encounter, data.effective_at, "effective_at")
        return self._save_new(Observation(patient_id=patient.id, **data.model_dump()))


class ConditionService(_RecordService[Condition]):
    label = "Condition"
    repository_class = ConditionRepository

    def list_for_patient(self, patient_id: uuid.UUID, params: ConditionListParams):
        return self._list(patient_id, params, status=params.status)

    def create(self, patient_id: uuid.UUID, data: ConditionCreate) -> Condition:
        patient = self._context.patient_for_recording(patient_id)
        encounter = self._context.encounter_for_recording(patient, data.encounter_id)
        values = data.model_dump()
        values["recorded_at"] = data.recorded_at or utc_now()
        for field in ("onset_at", "resolved_at", "recorded_at"):
            check_not_before_birth(patient, values[field], field)
        check_not_before_encounter(encounter, values["recorded_at"], "recorded_at")
        return self._save_new(Condition(patient_id=patient.id, **values))

    def update(self, condition_id: uuid.UUID, data: ConditionUpdate) -> Condition:
        condition = self._get_or_404(condition_id, for_update=True)
        changes = data.model_dump(exclude_unset=True)
        status = ConditionStatus(changes.get("status", condition.status))

        if "status" in changes:
            ensure_transition(f"Condition {condition.id}", condition.status, status, CONDITION_TRANSITIONS)
            if status == ConditionStatus.ACTIVE:
                changes.setdefault("resolved_at", None)  # recurrence clears the resolution date
        resolved_at = changes.get("resolved_at", condition.resolved_at)
        if resolved_at is not None:
            if status not in (ConditionStatus.RESOLVED, ConditionStatus.HISTORICAL):
                raise BusinessValidationError(
                    "resolved_at is only allowed for RESOLVED or HISTORICAL conditions", field="resolved_at"
                )
            if condition.onset_at and resolved_at < condition.onset_at:
                raise BusinessValidationError("resolved_at cannot be before onset_at", field="resolved_at")

        for field, value in changes.items():
            setattr(condition, field, value.value if isinstance(value, ConditionStatus) else value)
        return self._save(condition)


class AllergyService(_RecordService[Allergy]):
    label = "Allergy"
    repository_class = AllergyRepository

    def list_for_patient(self, patient_id: uuid.UUID, params: AllergyListParams):
        return self._list(patient_id, params, status=params.status)

    def create(self, patient_id: uuid.UUID, data: AllergyCreate) -> Allergy:
        patient = self._context.patient_for_recording(patient_id)
        encounter = self._context.encounter_for_recording(patient, data.encounter_id)
        values = data.model_dump()
        values["recorded_at"] = data.recorded_at or utc_now()
        for field in ("onset_at", "recorded_at"):
            check_not_before_birth(patient, values[field], field)
        check_not_before_encounter(encounter, values["recorded_at"], "recorded_at")
        if data.status == AllergyStatus.ACTIVE:
            self._ensure_no_other_active(patient.id, data.substance)
        return self._save_new(Allergy(patient_id=patient.id, **values))

    def update(self, allergy_id: uuid.UUID, data: AllergyUpdate) -> Allergy:
        allergy = self._get_or_404(allergy_id, for_update=True)
        changes = data.model_dump(exclude_unset=True)
        if "status" in changes:
            target = changes["status"]
            ensure_transition(f"Allergy {allergy.id}", allergy.status, target, ALLERGY_TRANSITIONS)
            if target == AllergyStatus.ACTIVE:
                self._ensure_no_other_active(allergy.patient_id, allergy.substance, exclude_id=allergy.id)
        for field, value in changes.items():
            setattr(allergy, field, value)
        return self._save(allergy)

    def _ensure_no_other_active(
        self, patient_id: uuid.UUID, substance: str, exclude_id: uuid.UUID | None = None
    ) -> None:
        existing = self._repository.active_for_substance(patient_id, substance, exclude_id=exclude_id)
        if existing is not None:
            raise ConflictError(
                f"The patient already has an active allergy to '{existing.substance}' ({existing.id})."
            )


class ClinicalNoteService(_RecordService[ClinicalNote]):
    label = "Clinical note"
    repository_class = ClinicalNoteRepository

    def list_for_patient(self, patient_id: uuid.UUID, params: ClinicalNoteListParams):
        return self._list(patient_id, params, encounter_id=params.encounter_id, note_type=params.note_type)

    def create(self, patient_id: uuid.UUID, data: ClinicalNoteCreate) -> ClinicalNote:
        patient = self._context.patient_for_recording(patient_id)
        encounter = self._context.encounter_for_recording(patient, data.encounter_id)
        values = data.model_dump()
        values["authored_at"] = data.authored_at or utc_now()
        values["author_staff_id"], values["author_name"] = self._directory.person(
            data.author_staff_id, data.author_name, "author_staff_id"
        )
        check_not_before_birth(patient, values["authored_at"], "authored_at")
        check_not_before_encounter(encounter, values["authored_at"], "authored_at")
        return self._save_new(ClinicalNote(patient_id=patient.id, **values))
