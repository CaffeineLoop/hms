"""Prescriptions. See app/models/prescription.py for the lifecycle.

Rules:
- created as DRAFT (with at least one item) for an ACTIVE patient, within an
  IN_PROGRESS/FINISHED encounter of that patient;
- items can be added and notes edited only while DRAFT;
- activating (issuing) requires the patient to still be ACTIVE;
- every status change goes through PRESCRIPTION_TRANSITIONS (409 otherwise).
No dispensing or stock handling (later pharmacy stage).
"""

import uuid

from sqlalchemy.orm import Session

from app.core.clock import now_not_before as not_before
from app.core.clock import utc_now
from app.core.errors import ConflictError, NotFoundError
from app.models.clinical_base import format_identifier
from app.models.prescription import (
    PRESCRIPTION_PREFIX,
    PRESCRIPTION_TRANSITIONS,
    Prescription,
    PrescriptionItem,
    PrescriptionStatus,
    prescription_number_seq,
)
from app.repositories.clinical_repository import PrescriptionRepository, SequenceRepository
from app.schemas.diagnostics import (
    CancelRequest,
    PrescriptionCreate,
    PrescriptionItemCreate,
    PrescriptionListParams,
    PrescriptionUpdate,
)
from app.services.clinical_common import (
    ClinicalContext,
    check_not_before_birth,
    check_not_before_encounter,
    ensure_transition,
)
from app.services.staff_directory import StaffDirectory


class PrescriptionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._prescriptions = PrescriptionRepository(session)
        self._sequences = SequenceRepository(session)
        self._context = ClinicalContext(session)
        self._directory = StaffDirectory(session)

    def get(self, prescription_id: uuid.UUID) -> Prescription:
        return self._get(prescription_id)

    def list_for_patient(
        self, patient_id: uuid.UUID, params: PrescriptionListParams
    ) -> tuple[list[Prescription], int]:
        self._context.patient(patient_id)
        return self._prescriptions.list_for_patient(
            patient_id,
            filters={"status": params.status, "encounter_id": params.encounter_id},
            limit=params.limit,
            offset=params.offset,
        )

    def create(self, patient_id: uuid.UUID, data: PrescriptionCreate) -> Prescription:
        patient = self._context.patient_for_recording(patient_id)
        encounter = self._context.encounter_for_recording(patient, data.encounter_id)
        prescribed_at = data.prescribed_at or utc_now()
        check_not_before_birth(patient, prescribed_at, "prescribed_at")
        check_not_before_encounter(encounter, prescribed_at, "prescribed_at")
        prescriber_staff_id, prescriber_name = self._directory.person(
            data.prescriber_staff_id, data.prescriber_name, "prescriber_staff_id"
        )
        prescription = Prescription(
            patient_id=patient.id,
            encounter_id=encounter.id,
            prescription_number=format_identifier(
                PRESCRIPTION_PREFIX, self._sequences.next_value(prescription_number_seq)
            ),
            prescriber_name=prescriber_name,
            prescriber_staff_id=prescriber_staff_id,
            status=PrescriptionStatus.DRAFT.value,
            prescribed_at=prescribed_at,
            notes=data.notes,
        )
        self._prescriptions.add(prescription)
        for line_number, item in enumerate(data.items, start=1):
            self._prescriptions.add_item(self._item(prescription, line_number, item))
        return self._save(prescription)

    def add_item(self, prescription_id: uuid.UUID, data: PrescriptionItemCreate) -> Prescription:
        prescription = self._get(prescription_id, for_update=True)
        self._require_draft(prescription, "items can only be added")
        next_line = max((item.line_number for item in prescription.items), default=0) + 1
        self._prescriptions.add_item(self._item(prescription, next_line, data))
        return self._save(prescription)

    def update(self, prescription_id: uuid.UUID, data: PrescriptionUpdate) -> Prescription:
        prescription = self._get(prescription_id, for_update=True)
        self._require_draft(prescription, "it can only be edited")
        prescription.notes = data.notes
        return self._save(prescription)

    def activate(self, prescription_id: uuid.UUID) -> Prescription:
        prescription = self._get(prescription_id, for_update=True)
        self._transition(prescription, PrescriptionStatus.ACTIVE)
        if prescription.status == PrescriptionStatus.DRAFT:
            if not prescription.items:
                raise ConflictError(f"Prescription {prescription.prescription_number} has no items.")
            self._context.patient_for_recording(prescription.patient_id)
            prescription.activated_at = not_before(prescription.prescribed_at)
        prescription.status = PrescriptionStatus.ACTIVE.value  # also resumes ON_HOLD
        return self._save(prescription)

    def hold(self, prescription_id: uuid.UUID) -> Prescription:
        return self._simple_transition(prescription_id, PrescriptionStatus.ON_HOLD)

    def resume(self, prescription_id: uuid.UUID) -> Prescription:
        prescription = self._get(prescription_id, for_update=True)
        if prescription.status != PrescriptionStatus.ON_HOLD:
            raise ConflictError(
                f"Prescription {prescription.prescription_number} is {prescription.status}; only ON_HOLD "
                "prescriptions can be resumed."
            )
        return self.activate(prescription_id)

    def complete(self, prescription_id: uuid.UUID) -> Prescription:
        prescription = self._get(prescription_id, for_update=True)
        self._transition(prescription, PrescriptionStatus.COMPLETED)
        prescription.status = PrescriptionStatus.COMPLETED.value
        prescription.completed_at = not_before(prescription.activated_at)
        return self._save(prescription)

    def cancel(self, prescription_id: uuid.UUID, data: CancelRequest) -> Prescription:
        prescription = self._get(prescription_id, for_update=True)
        self._transition(prescription, PrescriptionStatus.CANCELLED)
        prescription.status = PrescriptionStatus.CANCELLED.value
        prescription.cancelled_at = utc_now()
        prescription.cancellation_reason = data.reason
        return self._save(prescription)

    # --- helpers ------------------------------------------------------------------

    @staticmethod
    def _item(prescription: Prescription, line_number: int, data: PrescriptionItemCreate) -> PrescriptionItem:
        return PrescriptionItem(prescription_id=prescription.id, line_number=line_number, **data.model_dump())

    def _simple_transition(self, prescription_id: uuid.UUID, target: PrescriptionStatus) -> Prescription:
        prescription = self._get(prescription_id, for_update=True)
        self._transition(prescription, target)
        prescription.status = target.value
        return self._save(prescription)

    def _require_draft(self, prescription: Prescription, action: str) -> None:
        if prescription.status != PrescriptionStatus.DRAFT:
            raise ConflictError(
                f"Prescription {prescription.prescription_number} is {prescription.status}; {action} while DRAFT."
            )

    def _transition(self, prescription: Prescription, target: PrescriptionStatus) -> None:
        ensure_transition(
            f"Prescription {prescription.prescription_number}", prescription.status, target, PRESCRIPTION_TRANSITIONS
        )

    def _save(self, prescription: Prescription) -> Prescription:
        self._session.commit()
        self._session.refresh(prescription)
        return prescription

    def _get(self, prescription_id: uuid.UUID, *, for_update: bool = False) -> Prescription:
        prescription = self._prescriptions.get(prescription_id, for_update=for_update)
        if prescription is None:
            raise NotFoundError(f"Prescription {prescription_id} not found.")
        return prescription
