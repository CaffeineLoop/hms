"""API contracts for Stage 4 hospital workflows: appointments, admissions and tasks."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.encounter import EncounterType
from app.models.workflow import (
    AdmissionStatus,
    AdmissionType,
    AppointmentStatus,
    DischargeDisposition,
    TaskPriority,
    TaskStatus,
    WorkflowType,
)
from app.schemas.common import (
    AnyClinicalTimestamp,
    OptionalText1000,
    PageParams,
    PastClinicalTimestamp,
    Text200,
    Text500,
    optional_text,
)

OptionalText2000 = optional_text(2000)
OptionalText100000 = optional_text(100_000)
Bed = optional_text(30)


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class _Window(PageParams):
    scheduled_from: AnyClinicalTimestamp | None = None
    scheduled_to: AnyClinicalTimestamp | None = None

    @model_validator(mode="after")
    def _range(self):
        if self.scheduled_from and self.scheduled_to and self.scheduled_to < self.scheduled_from:
            raise ValueError("scheduled_to cannot be before scheduled_from")
        return self


# --- appointments ----------------------------------------------------------------------


class AppointmentCreate(_Input):
    department_id: uuid.UUID
    staff_id: uuid.UUID | None = Field(default=None, description="Clinician; must work in the department")
    reason: Text500
    scheduled_start: AnyClinicalTimestamp = Field(description="Cannot be in the past (5 min tolerance)")
    duration_minutes: int = Field(default=15, ge=5, le=480)
    notes: OptionalText1000 = None


class AppointmentStartConsultation(_Input):
    encounter_type: Literal[EncounterType.OPD, EncounterType.FOLLOW_UP] = EncounterType.OPD
    attending_staff_id: uuid.UUID | None = Field(
        default=None, description="Defaults to the appointment's clinician"
    )


class AppointmentComplete(_Input):
    summary: optional_text(10_000) = None


class AppointmentRead(_Output):
    id: uuid.UUID
    patient_id: uuid.UUID
    department_id: uuid.UUID
    staff_id: uuid.UUID | None
    encounter_id: uuid.UUID | None
    reason: str
    scheduled_start: datetime
    duration_minutes: int
    status: AppointmentStatus
    notes: str | None
    confirmed_at: datetime | None
    checked_in_at: datetime | None
    consultation_started_at: datetime | None
    completed_at: datetime | None
    no_show_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime


class PatientAppointmentListParams(PageParams):
    status: AppointmentStatus | None = None


class AppointmentSearchParams(_Window):
    """Hospital-wide schedule (e.g. a clinician's or department's day list)."""

    staff_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None
    status: AppointmentStatus | None = None


# --- admissions ------------------------------------------------------------------------


class AdmissionCreate(_Input):
    department_id: uuid.UUID = Field(description="Ward / unit requested")
    bed: Bed = None
    admission_type: AdmissionType
    reason: Text500
    requested_by_staff_id: uuid.UUID | None = Field(default=None, description="Defaults to the caller (Stage 6)")
    requested_at: PastClinicalTimestamp | None = Field(default=None, description="Defaults to now")
    attending_staff_id: uuid.UUID | None = None


class AdmissionApprove(_Input):
    approved_by_staff_id: uuid.UUID | None = Field(default=None, description="Defaults to the caller (Stage 6)")


class AdmissionAdmit(_Input):
    bed: Bed = None
    attending_staff_id: uuid.UUID | None = None
    admitted_at: PastClinicalTimestamp | None = Field(default=None, description="Defaults to now")


class AdmissionTransferCreate(_Input):
    to_department_id: uuid.UUID
    to_bed: Bed = None
    reason: Text500
    transferred_by_staff_id: uuid.UUID | None = None
    transferred_at: PastClinicalTimestamp | None = Field(default=None, description="Defaults to now")


class AdmissionDischarge(_Input):
    disposition: DischargeDisposition
    discharge_summary: OptionalText100000 = None
    discharged_at: PastClinicalTimestamp | None = Field(default=None, description="Defaults to now")


class AdmissionTransferRead(_Output):
    id: uuid.UUID
    admission_id: uuid.UUID
    patient_id: uuid.UUID
    from_department_id: uuid.UUID
    to_department_id: uuid.UUID
    from_bed: str | None
    to_bed: str | None
    reason: str
    transferred_at: datetime
    transferred_by_staff_id: uuid.UUID | None
    created_at: datetime


class AdmissionSummaryRead(_Output):
    id: uuid.UUID
    patient_id: uuid.UUID
    department_id: uuid.UUID
    bed: str | None
    encounter_id: uuid.UUID | None
    admission_type: AdmissionType
    reason: str
    status: AdmissionStatus
    requested_by_staff_id: uuid.UUID
    requested_at: datetime
    approved_by_staff_id: uuid.UUID | None
    approved_at: datetime | None
    attending_staff_id: uuid.UUID | None
    admitted_at: datetime | None
    discharged_at: datetime | None
    discharge_disposition: DischargeDisposition | None
    discharge_summary: str | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime


class AdmissionRead(AdmissionSummaryRead):
    transfers: list[AdmissionTransferRead]


class PatientAdmissionListParams(PageParams):
    status: AdmissionStatus | None = None


class AdmissionSearchParams(PageParams):
    """Hospital-wide admissions list (e.g. a ward census: department_id + status=ADMITTED)."""

    department_id: uuid.UUID | None = None
    status: AdmissionStatus | None = None


# --- workflow tasks --------------------------------------------------------------------


class TaskCreate(_Input):
    workflow_type: WorkflowType
    title: Text200
    description: OptionalText2000 = None
    priority: TaskPriority = TaskPriority.NORMAL
    patient_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    due_at: AnyClinicalTimestamp | None = None
    created_by_staff_id: uuid.UUID | None = None
    assigned_staff_id: uuid.UUID | None = Field(default=None, description="Assign immediately (status ASSIGNED)")


class TaskUpdate(_Input):
    title: Text200 | None = None
    description: OptionalText2000 = None
    priority: TaskPriority | None = None
    due_at: AnyClinicalTimestamp | None = None

    @model_validator(mode="after")
    def _check(self) -> "TaskUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        for field in ("title", "priority"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class TaskAssign(_Input):
    staff_id: uuid.UUID


class TaskComplete(_Input):
    completion_notes: OptionalText2000 = None


class TaskRead(_Output):
    id: uuid.UUID
    patient_id: uuid.UUID | None
    department_id: uuid.UUID | None
    workflow_type: WorkflowType
    title: str
    description: str | None
    priority: TaskPriority
    status: TaskStatus
    due_at: datetime | None
    created_by_staff_id: uuid.UUID | None
    assigned_staff_id: uuid.UUID | None
    assigned_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    completion_notes: str | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime


class TaskSearchParams(PageParams):
    status: TaskStatus | None = None
    assigned_staff_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    priority: TaskPriority | None = None
    workflow_type: WorkflowType | None = None

