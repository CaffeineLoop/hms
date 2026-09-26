"""Encounter lifecycle. See app/models/encounter.py for the state diagram."""

import uuid

from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.errors import BusinessValidationError, NotFoundError
from app.models.encounter import ENCOUNTER_TRANSITIONS, Encounter, EncounterStatus
from app.repositories.clinical_repository import EncounterRepository
from app.schemas.clinical import (
    EncounterCancel,
    EncounterCreate,
    EncounterFinish,
    EncounterListParams,
    EncounterStart,
)
from app.services.clinical_common import ClinicalContext, check_not_before_birth, ensure_transition
from app.services.staff_directory import StaffDirectory


class EncounterService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = EncounterRepository(session)
        self._context = ClinicalContext(session)
        self._directory = StaffDirectory(session)

    def get(self, encounter_id: uuid.UUID) -> Encounter:
        return self._get_or_404(encounter_id)

    def list_for_patient(self, patient_id: uuid.UUID, params: EncounterListParams) -> tuple[list[Encounter], int]:
        self._context.patient(patient_id)
        return self._repository.list_for_patient(
            patient_id,
            filters={"status": params.status, "encounter_type": params.encounter_type},
            limit=params.limit,
            offset=params.offset,
        )

    def create(self, patient_id: uuid.UUID, data: EncounterCreate) -> Encounter:
        patient = self._context.patient_for_recording(patient_id)
        start_at = data.start_at or utc_now()
        check_not_before_birth(patient, start_at, "start_at")
        attending = self._directory.optional_staff(data.attending_staff_id, "attending_staff_id")
        encounter = Encounter(
            attending_staff_id=attending.id if attending else None,
            patient_id=patient.id,
            encounter_type=data.encounter_type.value,
            status=data.status.value,
            reason=data.reason,
            start_at=start_at,
            end_at=data.end_at,
            summary=data.summary,
        )
        self._repository.add(encounter)
        self._session.commit()
        self._session.refresh(encounter)
        return encounter

    def start(self, encounter_id: uuid.UUID, data: EncounterStart) -> Encounter:
        encounter = self._get_or_404(encounter_id, for_update=True)
        self._transition(encounter, EncounterStatus.IN_PROGRESS)
        patient = self._context.patient_for_recording(encounter.patient_id)
        start_at = data.start_at or utc_now()
        check_not_before_birth(patient, start_at, "start_at")
        encounter.status = EncounterStatus.IN_PROGRESS.value
        encounter.start_at = start_at  # the actual start replaces the planned time
        return self._save(encounter)

    def finish(self, encounter_id: uuid.UUID, data: EncounterFinish) -> Encounter:
        encounter = self._get_or_404(encounter_id, for_update=True)
        self._transition(encounter, EncounterStatus.FINISHED)
        end_at = data.end_at or utc_now()
        if end_at < encounter.start_at:
            raise BusinessValidationError("end_at cannot be before the encounter's start_at", field="end_at")
        encounter.status = EncounterStatus.FINISHED.value
        encounter.end_at = end_at
        if data.summary is not None:
            encounter.summary = data.summary
        return self._save(encounter)

    def cancel(self, encounter_id: uuid.UUID, data: EncounterCancel) -> Encounter:
        encounter = self._get_or_404(encounter_id, for_update=True)
        self._transition(encounter, EncounterStatus.CANCELLED)
        encounter.status = EncounterStatus.CANCELLED.value
        encounter.cancellation_reason = data.reason
        return self._save(encounter)

    def _transition(self, encounter: Encounter, target: EncounterStatus) -> None:
        ensure_transition(f"Encounter {encounter.id}", encounter.status, target, ENCOUNTER_TRANSITIONS)

    def _save(self, encounter: Encounter) -> Encounter:
        self._session.commit()
        self._session.refresh(encounter)
        return encounter

    def _get_or_404(self, encounter_id: uuid.UUID, *, for_update: bool = False) -> Encounter:
        encounter = self._repository.get(encounter_id, for_update=for_update)
        if encounter is None:
            raise NotFoundError(f"Encounter {encounter_id} not found.")
        return encounter
