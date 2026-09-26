"""Admissions and ward transfers. See app/models/workflow.py for the state diagram.

Rules:
- requested for an ACTIVE patient with no other open admission (409; also enforced by a
  partial unique index), into an ACTIVE department, by an ACTIVE staff member;
- approval records the approving staff member; admission (patient must still be ACTIVE)
  opens an INPATIENT encounter, and discharge finishes it;
- transfers are allowed while ADMITTED/TRANSFERRED, must change the department or bed, and
  are recorded in admission_transfers; timestamps never go backwards
  (requested <= admitted <= transfers <= discharged, 422 otherwise);
- other status changes go through ADMISSION_TRANSITIONS (409 otherwise).
"""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.clock import now_not_before, utc_now
from app.core.errors import BusinessValidationError, ConflictError, NotFoundError
from app.models.encounter import Encounter, EncounterStatus, EncounterType
from app.models.workflow import (
    ADMISSION_TRANSITIONS,
    TRANSFERABLE_STATUSES,
    Admission,
    AdmissionStatus,
    AdmissionTransfer,
)
from app.repositories.clinical_repository import EncounterRepository
from app.repositories.workflow_repository import AdmissionRepository
from app.schemas.diagnostics import CancelRequest
from app.schemas.workflow import (
    AdmissionAdmit,
    AdmissionApprove,
    AdmissionCreate,
    AdmissionDischarge,
    AdmissionSearchParams,
    AdmissionTransferCreate,
    PatientAdmissionListParams,
)
from app.services.clinical_common import ClinicalContext, check_not_before_birth, ensure_transition
from app.services.staff_directory import StaffDirectory


class AdmissionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._admissions = AdmissionRepository(session)
        self._encounters = EncounterRepository(session)
        self._context = ClinicalContext(session)
        self._directory = StaffDirectory(session)

    def get(self, admission_id: uuid.UUID) -> Admission:
        return self._get(admission_id)

    def list_for_patient(self, patient_id: uuid.UUID, params: PatientAdmissionListParams):
        self._context.patient(patient_id)
        return self._admissions.search(
            filters={"patient_id": patient_id, "status": params.status}, limit=params.limit, offset=params.offset
        )

    def search(self, params: AdmissionSearchParams):
        return self._admissions.search(
            filters={"department_id": params.department_id, "status": params.status},
            limit=params.limit, offset=params.offset,
        )

    def create(self, patient_id: uuid.UUID, data: AdmissionCreate) -> Admission:
        patient = self._context.patient_for_recording(patient_id)
        if (existing := self._admissions.open_for_patient(patient.id)) is not None:
            raise ConflictError(f"Patient {patient.patient_number} already has an open admission ({existing.id}).")
        self._directory.active_department(data.department_id, "department_id")
        if data.requested_by_staff_id is None:
            raise BusinessValidationError("requested_by_staff_id is required", field="requested_by_staff_id")
        self._directory.active_staff(data.requested_by_staff_id, "requested_by_staff_id")
        self._directory.optional_staff(data.attending_staff_id, "attending_staff_id")
        values = data.model_dump()
        values["requested_at"] = data.requested_at or utc_now()
        check_not_before_birth(patient, values["requested_at"], "requested_at")
        admission = Admission(patient_id=patient.id, status=AdmissionStatus.REQUESTED.value, **values)
        self._admissions.add(admission)
        return self._save(admission)

    def approve(self, admission_id: uuid.UUID, data: AdmissionApprove) -> Admission:
        admission = self._transition(admission_id, AdmissionStatus.APPROVED)
        if data.approved_by_staff_id is None:
            raise BusinessValidationError("approved_by_staff_id is required", field="approved_by_staff_id")
        self._directory.active_staff(data.approved_by_staff_id, "approved_by_staff_id")
        admission.approved_by_staff_id = data.approved_by_staff_id
        admission.approved_at = now_not_before(admission.requested_at)
        return self._save(admission)

    def admit(self, admission_id: uuid.UUID, data: AdmissionAdmit) -> Admission:
        # Validate, create the INPATIENT encounter, then change the status (the database
        # requires an ADMITTED admission to reference its encounter).
        admission = self._transition(admission_id, AdmissionStatus.ADMITTED, apply=False)
        self._context.patient_for_recording(admission.patient_id)
        admitted_at = data.admitted_at or now_not_before(admission.requested_at)
        self._not_before(admitted_at, admission.requested_at, "admitted_at", "the admission request")
        if data.attending_staff_id is not None:
            admission.attending_staff_id = self._directory.active_staff(data.attending_staff_id, "attending_staff_id").id
        if data.bed is not None:
            admission.bed = data.bed
        encounter = Encounter(
            patient_id=admission.patient_id,
            encounter_type=EncounterType.INPATIENT.value,
            status=EncounterStatus.IN_PROGRESS.value,
            reason=admission.reason,
            start_at=admitted_at,
            attending_staff_id=admission.attending_staff_id,
        )
        self._encounters.add(encounter)
        admission.status = AdmissionStatus.ADMITTED.value
        admission.encounter_id = encounter.id
        admission.admitted_at = admitted_at
        return self._save(admission)

    def transfer(self, admission_id: uuid.UUID, data: AdmissionTransferCreate) -> Admission:
        admission = self._get(admission_id, for_update=True)
        if admission.status not in TRANSFERABLE_STATUSES:
            raise ConflictError(f"Admission {admission.id} is {admission.status}; only admitted patients can be transferred.")
        self._directory.active_department(data.to_department_id, "to_department_id")
        self._directory.optional_staff(data.transferred_by_staff_id, "transferred_by_staff_id")
        to_bed = data.to_bed
        if data.to_department_id == admission.department_id and to_bed == admission.bed:
            raise BusinessValidationError("a transfer must change the department or the bed", field="to_department_id")
        transferred_at = data.transferred_at or now_not_before(self._last_movement(admission))
        self._not_before(transferred_at, self._last_movement(admission), "transferred_at", "the last admission/transfer")
        self._admissions.add_transfer(AdmissionTransfer(
            patient_id=admission.patient_id,
            admission_id=admission.id,
            from_department_id=admission.department_id,
            to_department_id=data.to_department_id,
            from_bed=admission.bed,
            to_bed=to_bed,
            reason=data.reason,
            transferred_at=transferred_at,
            transferred_by_staff_id=data.transferred_by_staff_id,
        ))
        admission.department_id = data.to_department_id
        admission.bed = to_bed
        admission.status = AdmissionStatus.TRANSFERRED.value
        return self._save(admission)

    def discharge(self, admission_id: uuid.UUID, data: AdmissionDischarge) -> Admission:
        admission = self._transition(admission_id, AdmissionStatus.DISCHARGED)
        discharged_at = data.discharged_at or now_not_before(self._last_movement(admission))
        self._not_before(discharged_at, self._last_movement(admission), "discharged_at", "the last admission/transfer")
        admission.discharged_at = discharged_at
        admission.discharge_disposition = data.disposition.value
        admission.discharge_summary = data.discharge_summary
        encounter = self._encounters.get(admission.encounter_id, for_update=True)
        if encounter.status == EncounterStatus.IN_PROGRESS:
            encounter.status = EncounterStatus.FINISHED.value
            encounter.end_at = max(discharged_at, encounter.start_at)
            if data.discharge_summary is not None:
                encounter.summary = data.discharge_summary
        return self._save(admission)

    def cancel(self, admission_id: uuid.UUID, data: CancelRequest) -> Admission:
        admission = self._transition(admission_id, AdmissionStatus.CANCELLED)
        admission.cancelled_at = utc_now()
        admission.cancellation_reason = data.reason
        return self._save(admission)

    # --- helpers ------------------------------------------------------------------

    @staticmethod
    def _last_movement(admission: Admission) -> datetime:
        times = [admission.admitted_at or admission.requested_at] + [t.transferred_at for t in admission.transfers]
        return max(times)

    @staticmethod
    def _not_before(value: datetime, earliest: datetime, field: str, what: str) -> None:
        if value < earliest:
            raise BusinessValidationError(f"{field} cannot be before {what}", field=field)

    def _transition(self, admission_id: uuid.UUID, target: AdmissionStatus, *, apply: bool = True) -> Admission:
        admission = self._get(admission_id, for_update=True)
        ensure_transition(f"Admission {admission.id}", admission.status, target, ADMISSION_TRANSITIONS)
        if apply:
            admission.status = target.value
        return admission

    def _save(self, admission: Admission) -> Admission:
        self._session.commit()
        self._session.refresh(admission)
        return admission

    def _get(self, admission_id: uuid.UUID, *, for_update: bool = False) -> Admission:
        admission = self._admissions.get(admission_id, for_update=for_update)
        if admission is None:
            raise NotFoundError(f"Admission {admission_id} not found.")
        return admission
