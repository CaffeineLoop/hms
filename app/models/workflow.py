"""Hospital workflows (Stage 4): appointments, admissions (with transfers) and work tasks.

Appointment lifecycle:
    REQUESTED ─confirm─> CONFIRMED ─check-in─> CHECKED_IN ─start─> IN_CONSULTATION ─complete─> COMPLETED
        │                   │  └──no-show──> NO_SHOW          │
        └──────cancel───────┴──────────cancel─────────────────┘──> CANCELLED
  Starting the consultation opens an encounter (IN_PROGRESS); completing finishes it.

Admission lifecycle:
    REQUESTED ─approve─> APPROVED ─admit─> ADMITTED ─transfer─> TRANSFERRED ─transfer─> TRANSFERRED
        │                   │                  │                     │
        └──cancel───────────┴──> CANCELLED     └──────discharge──────┴──> DISCHARGED
  Admitting opens an INPATIENT encounter; discharging finishes it. A patient has at most
  one open admission (enforced by a partial unique index). Every transfer is kept in
  admission_transfers.

Workflow task lifecycle:
    OPEN ─assign─> ASSIGNED ─start─> IN_PROGRESS ─complete─> COMPLETED
    (re-assignment to another staff member is allowed while ASSIGNED / IN_PROGRESS without a
    status change; cancel from any non-terminal state)

No authorization: any caller may perform any transition until Stage 5.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.clinical_base import ClinicalRecordMixin, in_list, same_patient_encounter_fk, same_patient_fk
from app.models.staff import staff_fk


def _department_fk() -> ForeignKey:
    return ForeignKey("departments.id", ondelete="RESTRICT")


# --- appointments ----------------------------------------------------------------------


class AppointmentStatus(StrEnum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    IN_CONSULTATION = "IN_CONSULTATION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


APPOINTMENT_TRANSITIONS: dict[AppointmentStatus, frozenset[AppointmentStatus]] = {
    AppointmentStatus.REQUESTED: frozenset({AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED}),
    AppointmentStatus.CONFIRMED: frozenset(
        {AppointmentStatus.CHECKED_IN, AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW}
    ),
    AppointmentStatus.CHECKED_IN: frozenset({AppointmentStatus.IN_CONSULTATION, AppointmentStatus.CANCELLED}),
    AppointmentStatus.IN_CONSULTATION: frozenset({AppointmentStatus.COMPLETED}),
    AppointmentStatus.COMPLETED: frozenset(),
    AppointmentStatus.CANCELLED: frozenset(),
    AppointmentStatus.NO_SHOW: frozenset(),
}


class Appointment(ClinicalRecordMixin, Base):
    __tablename__ = "appointments"

    department_id: Mapped[uuid.UUID] = mapped_column(_department_fk())
    staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())
    encounter_id: Mapped[uuid.UUID | None] = mapped_column()
    reason: Mapped[str] = mapped_column(String(500))
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(String(1000))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consultation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    no_show_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        same_patient_encounter_fk(),
        CheckConstraint(in_list("status", AppointmentStatus), name="status_valid"),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        CheckConstraint("duration_minutes BETWEEN 5 AND 480", name="duration_valid"),
        CheckConstraint(
            "(status = 'CANCELLED') = (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)",
            name="cancellation_matches_status",
        ),
        CheckConstraint("(status = 'NO_SHOW') = (no_show_at IS NOT NULL)", name="no_show_matches_status"),
        CheckConstraint("(status = 'COMPLETED') = (completed_at IS NOT NULL)", name="completion_matches_status"),
        CheckConstraint(
            "(status IN ('IN_CONSULTATION', 'COMPLETED')) = (encounter_id IS NOT NULL)",
            name="encounter_matches_status",
        ),
        Index("ix_appointments_patient_id_scheduled_start", "patient_id", "scheduled_start"),
        Index("ix_appointments_staff_id_scheduled_start", "staff_id", "scheduled_start"),
        Index("ix_appointments_department_id_scheduled_start", "department_id", "scheduled_start"),
        Index("ix_appointments_status", "status"),
    )


# --- admissions ------------------------------------------------------------------------


class AdmissionStatus(StrEnum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ADMITTED = "ADMITTED"
    TRANSFERRED = "TRANSFERRED"
    DISCHARGED = "DISCHARGED"
    CANCELLED = "CANCELLED"


ADMISSION_TRANSITIONS: dict[AdmissionStatus, frozenset[AdmissionStatus]] = {
    AdmissionStatus.REQUESTED: frozenset({AdmissionStatus.APPROVED, AdmissionStatus.CANCELLED}),
    AdmissionStatus.APPROVED: frozenset({AdmissionStatus.ADMITTED, AdmissionStatus.CANCELLED}),
    AdmissionStatus.ADMITTED: frozenset({AdmissionStatus.TRANSFERRED, AdmissionStatus.DISCHARGED}),
    AdmissionStatus.TRANSFERRED: frozenset({AdmissionStatus.DISCHARGED}),
    AdmissionStatus.DISCHARGED: frozenset(),
    AdmissionStatus.CANCELLED: frozenset(),
}
OPEN_ADMISSION_STATUSES = ("REQUESTED", "APPROVED", "ADMITTED", "TRANSFERRED")
# A patient can be moved again after a transfer (TRANSFERRED -> TRANSFERRED is a new transfer,
# handled explicitly by the service rather than as a status change).
TRANSFERABLE_STATUSES = frozenset({AdmissionStatus.ADMITTED, AdmissionStatus.TRANSFERRED})


class AdmissionType(StrEnum):
    ELECTIVE = "ELECTIVE"
    EMERGENCY = "EMERGENCY"


class DischargeDisposition(StrEnum):
    HOME = "HOME"
    REFERRED_OUT = "REFERRED_OUT"
    AGAINST_MEDICAL_ADVICE = "AGAINST_MEDICAL_ADVICE"
    DECEASED = "DECEASED"
    OTHER = "OTHER"


class Admission(ClinicalRecordMixin, Base):
    __tablename__ = "admissions"

    department_id: Mapped[uuid.UUID] = mapped_column(_department_fk())  # current ward/unit
    bed: Mapped[str | None] = mapped_column(String(30))
    encounter_id: Mapped[uuid.UUID | None] = mapped_column()
    admission_type: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20))
    requested_by_staff_id: Mapped[uuid.UUID] = mapped_column(staff_fk())
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attending_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discharged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discharge_disposition: Mapped[str | None] = mapped_column(String(30))
    discharge_summary: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))

    transfers: Mapped[list["AdmissionTransfer"]] = relationship(
        primaryjoin="Admission.id == foreign(AdmissionTransfer.admission_id)",
        order_by="(AdmissionTransfer.transferred_at, AdmissionTransfer.created_at)",
        lazy="selectin",
        viewonly=True,
    )

    __table_args__ = (
        UniqueConstraint("id", "patient_id", name="uq_admissions_id_patient_id"),
        same_patient_encounter_fk(),
        CheckConstraint(in_list("status", AdmissionStatus), name="status_valid"),
        CheckConstraint(in_list("admission_type", AdmissionType), name="admission_type_valid"),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        CheckConstraint(
            f"discharge_disposition IS NULL OR {in_list('discharge_disposition', DischargeDisposition)}",
            name="discharge_disposition_valid",
        ),
        CheckConstraint(
            "(approved_at IS NULL) = (approved_by_staff_id IS NULL)"
            " AND ((status = 'REQUESTED') = (approved_at IS NULL) OR status = 'CANCELLED')",
            name="approval_matches_status",
        ),
        CheckConstraint(
            "(status IN ('ADMITTED', 'TRANSFERRED', 'DISCHARGED'))"
            " = (admitted_at IS NOT NULL AND encounter_id IS NOT NULL)",
            name="admission_matches_status",
        ),
        CheckConstraint(
            "(status = 'DISCHARGED') = (discharged_at IS NOT NULL AND discharge_disposition IS NOT NULL)",
            name="discharge_matches_status",
        ),
        CheckConstraint(
            "(status = 'CANCELLED') = (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)",
            name="cancellation_matches_status",
        ),
        CheckConstraint(
            "(approved_at IS NULL OR approved_at >= requested_at)"
            " AND (admitted_at IS NULL OR admitted_at >= requested_at)"
            " AND (discharged_at IS NULL OR discharged_at >= admitted_at)",
            name="timestamps_ordered",
        ),
        Index("ix_admissions_patient_id_requested_at", "patient_id", "requested_at"),
        Index("ix_admissions_department_id_status", "department_id", "status"),
    )


Index(
    "uq_admissions_one_open_per_patient",
    Admission.patient_id,
    unique=True,
    postgresql_where=Admission.status.in_(OPEN_ADMISSION_STATUSES),
)


class AdmissionTransfer(ClinicalRecordMixin, Base):
    __tablename__ = "admission_transfers"

    admission_id: Mapped[uuid.UUID] = mapped_column()
    from_department_id: Mapped[uuid.UUID] = mapped_column(_department_fk())
    to_department_id: Mapped[uuid.UUID] = mapped_column(_department_fk())
    from_bed: Mapped[str | None] = mapped_column(String(30))
    to_bed: Mapped[str | None] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(String(500))
    transferred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    transferred_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())

    __table_args__ = (
        same_patient_fk("admission_id", "admissions"),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        CheckConstraint(
            "from_department_id <> to_department_id OR from_bed IS DISTINCT FROM to_bed",
            name="location_changes",
        ),
        Index("ix_admission_transfers_admission_id", "admission_id"),
        Index("ix_admission_transfers_patient_id_transferred_at", "patient_id", "transferred_at"),
    )


# --- workflow tasks --------------------------------------------------------------------


class TaskStatus(StrEnum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.OPEN: frozenset({TaskStatus.ASSIGNED, TaskStatus.CANCELLED}),
    TaskStatus.ASSIGNED: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED}),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.COMPLETED, TaskStatus.CANCELLED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


class TaskPriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class WorkflowType(StrEnum):
    SAMPLE_COLLECTION = "SAMPLE_COLLECTION"
    MEDICATION_ADMINISTRATION = "MEDICATION_ADMINISTRATION"
    NURSING_CARE = "NURSING_CARE"
    PATIENT_TRANSPORT = "PATIENT_TRANSPORT"
    DISCHARGE_PREPARATION = "DISCHARGE_PREPARATION"
    FOLLOW_UP = "FOLLOW_UP"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    OTHER = "OTHER"


class WorkflowTask(Base):
    __tablename__ = "workflow_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.id", ondelete="RESTRICT"))
    department_id: Mapped[uuid.UUID | None] = mapped_column(_department_fk())
    workflow_type: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(2000))
    priority: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())
    assigned_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completion_notes: Mapped[str | None] = mapped_column(String(2000))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(in_list("workflow_type", WorkflowType), name="workflow_type_valid"),
        CheckConstraint(in_list("priority", TaskPriority), name="priority_valid"),
        CheckConstraint(in_list("status", TaskStatus), name="status_valid"),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint(
            "(status NOT IN ('ASSIGNED', 'IN_PROGRESS', 'COMPLETED') OR assigned_staff_id IS NOT NULL)"
            " AND (assigned_staff_id IS NULL) = (assigned_at IS NULL)",
            name="assignment_matches_status",
        ),
        CheckConstraint("(status = 'COMPLETED') = (completed_at IS NOT NULL)", name="completion_matches_status"),
        CheckConstraint(
            "(status = 'CANCELLED') = (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)",
            name="cancellation_matches_status",
        ),
        Index("ix_workflow_tasks_assigned_staff_id_status", "assigned_staff_id", "status"),
        Index("ix_workflow_tasks_patient_id", "patient_id"),
        Index("ix_workflow_tasks_status_priority", "status", "priority"),
    )
