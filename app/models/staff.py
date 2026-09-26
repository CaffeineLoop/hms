"""Departments and staff (Stage 4).

Staff are hospital personnel, not user accounts: there are no logins, roles or permissions
here (Stage 5). `designation` describes the job, it grants nothing.

Clinical records created from Stage 4 onwards reference staff by id (e.g.
clinical_notes.author_staff_id) and keep a snapshot of the name in their existing text
column, so historical/imported records without a staff row remain valid.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.clinical_base import in_list


class RecordStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Designation(StrEnum):
    DOCTOR = "DOCTOR"
    CLINICAL_OFFICER = "CLINICAL_OFFICER"
    NURSE = "NURSE"
    MIDWIFE = "MIDWIFE"
    LAB_TECHNICIAN = "LAB_TECHNICIAN"
    PHARMACIST = "PHARMACIST"
    RADIOGRAPHER = "RADIOGRAPHER"
    RECEPTIONIST = "RECEPTIONIST"
    ADMINISTRATOR = "ADMINISTRATOR"
    OTHER = "OTHER"


class _Timestamps:
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Department(_Timestamps, Base):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), default=RecordStatus.ACTIVE.value)

    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint(in_list("status", RecordStatus), name="status_valid"),
    )


Index("uq_departments_lower_name", func.lower(Department.name), unique=True)


class Staff(_Timestamps, Base):
    __tablename__ = "staff"

    employee_code: Mapped[str] = mapped_column(String(20), unique=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    designation: Mapped[str] = mapped_column(String(20))
    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))
    status: Mapped[str] = mapped_column(String(10), default=RecordStatus.ACTIVE.value)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    __table_args__ = (
        CheckConstraint(r"employee_code ~ '^[A-Z0-9][A-Z0-9-]{1,19}$'", name="employee_code_format"),
        CheckConstraint("length(btrim(first_name)) > 0", name="first_name_not_blank"),
        CheckConstraint("length(btrim(last_name)) > 0", name="last_name_not_blank"),
        CheckConstraint(in_list("designation", Designation), name="designation_valid"),
        CheckConstraint(in_list("status", RecordStatus), name="status_valid"),
        CheckConstraint("(status = 'INACTIVE') = (deactivated_at IS NOT NULL)", name="deactivation_matches_status"),
        Index("ix_staff_department_id", "department_id"),
    )


Index("ix_staff_lower_name", func.lower(Staff.last_name), func.lower(Staff.first_name))
Index("uq_staff_lower_email", func.lower(Staff.email), unique=True, postgresql_where=Staff.email.is_not(None))


def staff_fk() -> ForeignKey:
    """Reference from another record to the staff member involved (never cascades)."""
    return ForeignKey("staff.id", ondelete="RESTRICT")
