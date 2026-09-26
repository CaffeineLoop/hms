"""Appointments. See app/models/workflow.py for the state diagram.

Rules:
- booked for an ACTIVE patient in an ACTIVE department; an optional clinician must be ACTIVE
  and belong to that department; the slot cannot be in the past (5 min tolerance);
- checking in and starting the consultation require the patient to still be ACTIVE;
- starting the consultation opens an IN_PROGRESS encounter (OPD / FOLLOW_UP) whose attending
  clinician is the appointment's clinician unless another is given; completing the
  appointment finishes that encounter if it is still open;
- every status change goes through APPOINTMENT_TRANSITIONS (409 otherwise).
"""

import uuid

from sqlalchemy.orm import Session

from app.core.clock import MAX_CLOCK_SKEW, now_not_before, utc_now
from app.core.errors import BusinessValidationError, NotFoundError
from app.models.encounter import Encounter, EncounterStatus
from app.models.workflow import APPOINTMENT_TRANSITIONS, Appointment, AppointmentStatus
from app.repositories.clinical_repository import EncounterRepository
from app.repositories.workflow_repository import AppointmentRepository
from app.schemas.diagnostics import CancelRequest
from app.schemas.workflow import (
    AppointmentComplete,
    AppointmentCreate,
    AppointmentSearchParams,
    AppointmentStartConsultation,
    PatientAppointmentListParams,
)
from app.services.clinical_common import ClinicalContext, ensure_transition
from app.services.staff_directory import StaffDirectory


class AppointmentService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._appointments = AppointmentRepository(session)
        self._encounters = EncounterRepository(session)
        self._context = ClinicalContext(session)
        self._directory = StaffDirectory(session)

    def get(self, appointment_id: uuid.UUID) -> Appointment:
        return self._get(appointment_id)

    def list_for_patient(self, patient_id: uuid.UUID, params: PatientAppointmentListParams):
        self._context.patient(patient_id)
        return self._appointments.search(
            filters={"patient_id": patient_id, "status": params.status},
            newest_first=True, limit=params.limit, offset=params.offset,
        )

    def search(self, params: AppointmentSearchParams):
        filters = {"staff_id": params.staff_id, "department_id": params.department_id,
                   "patient_id": params.patient_id, "status": params.status}
        return self._appointments.search(
            filters=filters, scheduled_from=params.scheduled_from, scheduled_to=params.scheduled_to,
            limit=params.limit, offset=params.offset,
        )

    def create(self, patient_id: uuid.UUID, data: AppointmentCreate) -> Appointment:
        patient = self._context.patient_for_recording(patient_id)
        self._directory.active_department(data.department_id, "department_id")
        if data.staff_id is not None:
            clinician = self._directory.active_staff(data.staff_id, "staff_id")
            if clinician.department_id != data.department_id:
                raise BusinessValidationError(
                    f"staff member {clinician.employee_code} does not work in the requested department",
                    field="staff_id",
                )
        if data.scheduled_start < utc_now() - MAX_CLOCK_SKEW:
            raise BusinessValidationError("scheduled_start cannot be in the past", field="scheduled_start")
        appointment = Appointment(patient_id=patient.id, status=AppointmentStatus.REQUESTED.value, **data.model_dump())
        self._appointments.add(appointment)
        return self._save(appointment)

    def confirm(self, appointment_id: uuid.UUID) -> Appointment:
        appointment = self._transition(appointment_id, AppointmentStatus.CONFIRMED)
        appointment.confirmed_at = now_not_before(appointment.created_at)
        return self._save(appointment)

    def check_in(self, appointment_id: uuid.UUID) -> Appointment:
        appointment = self._transition(appointment_id, AppointmentStatus.CHECKED_IN)
        self._context.patient_for_recording(appointment.patient_id)
        appointment.checked_in_at = now_not_before(appointment.confirmed_at)
        return self._save(appointment)

    def start_consultation(self, appointment_id: uuid.UUID, data: AppointmentStartConsultation) -> Appointment:
        # Validate first, create the encounter, and only then change the status: the database
        # requires an IN_CONSULTATION appointment to reference its encounter.
        appointment = self._transition(appointment_id, AppointmentStatus.IN_CONSULTATION, apply=False)
        self._context.patient_for_recording(appointment.patient_id)
        attending = self._directory.optional_staff(
            data.attending_staff_id or appointment.staff_id, "attending_staff_id"
        )
        started_at = now_not_before(appointment.checked_in_at)
        encounter = Encounter(
            patient_id=appointment.patient_id,
            encounter_type=data.encounter_type.value,
            status=EncounterStatus.IN_PROGRESS.value,
            reason=appointment.reason,
            start_at=started_at,
            attending_staff_id=attending.id if attending else None,
        )
        self._encounters.add(encounter)
        appointment.status = AppointmentStatus.IN_CONSULTATION.value
        appointment.encounter_id = encounter.id
        appointment.consultation_started_at = started_at
        return self._save(appointment)

    def complete(self, appointment_id: uuid.UUID, data: AppointmentComplete) -> Appointment:
        appointment = self._transition(appointment_id, AppointmentStatus.COMPLETED)
        completed_at = now_not_before(appointment.consultation_started_at)
        appointment.completed_at = completed_at
        encounter = self._encounters.get(appointment.encounter_id, for_update=True)
        if encounter.status == EncounterStatus.IN_PROGRESS:
            encounter.status = EncounterStatus.FINISHED.value
            encounter.end_at = max(completed_at, encounter.start_at)
            if data.summary is not None:
                encounter.summary = data.summary
        return self._save(appointment)

    def no_show(self, appointment_id: uuid.UUID) -> Appointment:
        appointment = self._transition(appointment_id, AppointmentStatus.NO_SHOW)
        appointment.no_show_at = utc_now()
        return self._save(appointment)

    def cancel(self, appointment_id: uuid.UUID, data: CancelRequest) -> Appointment:
        appointment = self._transition(appointment_id, AppointmentStatus.CANCELLED)
        appointment.cancelled_at = utc_now()
        appointment.cancellation_reason = data.reason
        return self._save(appointment)

    # --- helpers ------------------------------------------------------------------

    def _transition(self, appointment_id: uuid.UUID, target: AppointmentStatus, *, apply: bool = True) -> Appointment:
        appointment = self._get(appointment_id, for_update=True)
        ensure_transition(f"Appointment {appointment.id}", appointment.status, target, APPOINTMENT_TRANSITIONS)
        if apply:
            appointment.status = target.value
        return appointment

    def _save(self, appointment: Appointment) -> Appointment:
        self._session.commit()
        self._session.refresh(appointment)
        return appointment

    def _get(self, appointment_id: uuid.UUID, *, for_update: bool = False) -> Appointment:
        appointment = self._appointments.get(appointment_id, for_update=for_update)
        if appointment is None:
            raise NotFoundError(f"Appointment {appointment_id} not found.")
        return appointment
