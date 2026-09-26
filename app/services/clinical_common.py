"""Rules shared by every clinical-record service.

- A record can only be created for an existing (404) and ACTIVE (409) patient.
- A referenced encounter must exist and belong to that patient (422), and must have
  actually taken place - IN_PROGRESS or FINISHED (409).
- Clinical timestamps cannot precede the patient's birth (422). The birth day starts at
  midnight in the facility time zone (APP_TIMEZONE).
- A record linked to an encounter cannot be measured/documented before that encounter
  started (422). Onset dates are exempt: an illness usually begins before the visit.
- Status changes must follow the entity's transition table (409).
"""

import uuid
from datetime import datetime, time
from enum import StrEnum

from sqlalchemy.orm import Session

from app.core.clock import facility_timezone
from app.core.errors import BusinessValidationError, ConflictError, NotFoundError
from app.models.encounter import RECORDABLE_ENCOUNTER_STATUSES, Encounter
from app.models.patient import Patient, PatientStatus
from app.repositories.clinical_repository import EncounterRepository
from app.repositories.patient_repository import PatientRepository


class ClinicalContext:
    def __init__(self, session: Session) -> None:
        self._patients = PatientRepository(session)
        self._encounters = EncounterRepository(session)

    def patient(self, patient_id: uuid.UUID) -> Patient:
        patient = self._patients.get(patient_id)
        if patient is None:
            raise NotFoundError(f"Patient {patient_id} not found.")
        return patient

    def patient_for_recording(self, patient_id: uuid.UUID) -> Patient:
        patient = self.patient(patient_id)
        if patient.status != PatientStatus.ACTIVE:
            raise ConflictError(
                f"Patient {patient.patient_number} is inactive; new clinical records cannot be added."
            )
        return patient

    def encounter_for_recording(self, patient: Patient, encounter_id: uuid.UUID | None) -> Encounter | None:
        if encounter_id is None:
            return None
        encounter = self._encounters.get(encounter_id)
        if encounter is None or encounter.patient_id != patient.id:
            raise BusinessValidationError(
                f"encounter {encounter_id} does not exist for patient {patient.patient_number}",
                field="encounter_id",
            )
        if encounter.status not in RECORDABLE_ENCOUNTER_STATUSES:
            raise ConflictError(
                f"Encounter {encounter.id} is {encounter.status}; records can only be added to "
                "IN_PROGRESS or FINISHED encounters."
            )
        return encounter


def check_not_before_birth(patient: Patient, value: datetime | None, field: str) -> None:
    if value is None:
        return
    birth = datetime.combine(patient.date_of_birth, time.min, tzinfo=facility_timezone())
    if value < birth:
        raise BusinessValidationError(
            f"{field} cannot be before the patient's date of birth ({patient.date_of_birth.isoformat()})",
            field=field,
        )


def check_not_before_encounter(encounter: Encounter | None, value: datetime, field: str) -> None:
    if encounter is not None and value < encounter.start_at:
        raise BusinessValidationError(f"{field} cannot be before the encounter's start_at", field=field)


def ensure_transition[S: StrEnum](
    label: str, current: str, target: S, transitions: dict[S, frozenset[S]]
) -> None:
    current_status = type(target)(current)
    if target == current_status:
        raise ConflictError(f"{label} is already {target.value}.")
    if target not in transitions[current_status]:
        raise ConflictError(f"{label} cannot change from {current_status.value} to {target.value}.")
