"""Business rules for Patient Management.

Rules enforced here (the database enforces the structural ones as well):
- Patient IDs (PAT-000001) are system-generated; clients cannot choose or change them.
- A new or edited patient may not duplicate an existing patient: same first + last name
  (case-insensitive) and date of birth AND the same phone or email -> 409.
- Emergency contact: name and phone are given together; relationship needs a name.
- Patients are never deleted. Deactivation is an explicit, reasoned status change;
  deactivating an inactive patient (or reactivating an active one) is a 409.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.errors import BusinessValidationError, ConflictError, NotFoundError
from app.models.patient import Patient, PatientStatus, format_patient_number
from app.repositories.patient_repository import PatientRepository
from app.schemas.patient import PatientCreate, PatientListParams, PatientUpdate

_DUPLICATE_KEYS = ("first_name", "last_name", "date_of_birth", "phone", "email")


class PatientService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = PatientRepository(session)

    # --- queries -------------------------------------------------------------

    def get(self, patient_id: uuid.UUID) -> Patient:
        return self._get_or_404(patient_id)

    def search(self, params: PatientListParams) -> tuple[list[Patient], int]:
        return self._repository.search(
            search=params.q or None, status=params.status, limit=params.limit, offset=params.offset
        )

    # --- commands ------------------------------------------------------------

    def create(self, data: PatientCreate) -> Patient:
        values = data.model_dump()
        _check_emergency_contact(values)
        self._ensure_not_duplicate(values)

        patient = Patient(
            **values,
            patient_number=format_patient_number(self._repository.next_patient_number_value()),
            status=PatientStatus.ACTIVE.value,
        )
        self._repository.add(patient)
        self._session.commit()
        self._session.refresh(patient)  # loads server-generated timestamps
        return patient

    def update(self, patient_id: uuid.UUID, data: PatientUpdate) -> Patient:
        patient = self._get_or_404(patient_id, for_update=True)
        changes = data.model_dump(exclude_unset=True)

        merged = {column: getattr(patient, column) for column in _patient_columns()} | changes
        _check_emergency_contact(merged)
        if any(key in changes for key in _DUPLICATE_KEYS):
            self._ensure_not_duplicate(merged, exclude_id=patient.id)

        for field, value in changes.items():
            setattr(patient, field, value)
        self._session.commit()
        self._session.refresh(patient)  # picks up the new updated_at
        return patient

    def deactivate(self, patient_id: uuid.UUID, reason: str) -> Patient:
        patient = self._get_or_404(patient_id, for_update=True)
        if patient.status == PatientStatus.INACTIVE:
            raise ConflictError(f"Patient {patient.patient_number} is already inactive.")
        patient.status = PatientStatus.INACTIVE.value
        patient.deactivated_at = utc_now()
        patient.deactivation_reason = reason
        self._session.commit()
        self._session.refresh(patient)
        return patient

    def reactivate(self, patient_id: uuid.UUID) -> Patient:
        patient = self._get_or_404(patient_id, for_update=True)
        if patient.status == PatientStatus.ACTIVE:
            raise ConflictError(f"Patient {patient.patient_number} is already active.")
        patient.status = PatientStatus.ACTIVE.value
        patient.deactivated_at = None
        patient.deactivation_reason = None
        self._session.commit()
        self._session.refresh(patient)
        return patient

    # --- helpers -------------------------------------------------------------

    def _get_or_404(self, patient_id: uuid.UUID, *, for_update: bool = False) -> Patient:
        patient = self._repository.get(patient_id, for_update=for_update)
        if patient is None:
            raise NotFoundError(f"Patient {patient_id} not found.")
        return patient

    def _ensure_not_duplicate(self, values: dict[str, Any], exclude_id: uuid.UUID | None = None) -> None:
        duplicates = self._repository.find_duplicates(
            first_name=values["first_name"],
            last_name=values["last_name"],
            date_of_birth=values["date_of_birth"],
            phone=values.get("phone"),
            email=values.get("email"),
            exclude_id=exclude_id,
        )
        if duplicates:
            numbers = ", ".join(p.patient_number for p in duplicates)
            raise ConflictError(
                "A patient with the same name, date of birth and phone/email already exists: "
                f"{numbers}."
            )


def _patient_columns() -> list[str]:
    return [column.key for column in Patient.__table__.columns]


def _check_emergency_contact(values: dict[str, Any]) -> None:
    name = values.get("emergency_contact_name")
    phone = values.get("emergency_contact_phone")
    relationship = values.get("emergency_contact_relationship")
    if name and not phone:
        raise BusinessValidationError(
            "emergency_contact_phone is required when emergency_contact_name is given",
            field="emergency_contact_phone",
        )
    if (phone or relationship) and not name:
        raise BusinessValidationError(
            "emergency_contact_name is required when other emergency contact details are given",
            field="emergency_contact_name",
        )
