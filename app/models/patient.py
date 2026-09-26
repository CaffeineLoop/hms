"""Patient identity and demographics (Stage 1).

This table holds WHO the patient is, never WHAT happened to them clinically.
Encounters, diagnoses, allergies, observations, notes, etc. belong to later
stages and will reference `patients.id` through their own foreign keys.

Identifiers:
- `id`              internal UUID primary key; the only value other tables reference.
- `patient_number`  human-facing Patient ID (e.g. PAT-000001), generated from the
                    `patient_number_seq` PostgreSQL sequence and never reused.

Patients are never physically deleted; they are deactivated (status INACTIVE).
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Sequence,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PATIENT_NUMBER_PREFIX = "PAT-"
PATIENT_NUMBER_DIGITS = 6


class PatientStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Sex(StrEnum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


def format_patient_number(value: int) -> str:
    """1 -> 'PAT-000001'. Values past 999999 simply gain digits; they are never truncated."""
    if value < 1:
        raise ValueError("patient number sequence values start at 1")
    return f"{PATIENT_NUMBER_PREFIX}{value:0{PATIENT_NUMBER_DIGITS}d}"


patient_number_seq = Sequence("patient_number_seq", start=1, metadata=Base.metadata)


def _in_list(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    patient_number: Mapped[str] = mapped_column(String(20), unique=True)

    # Identity
    first_name: Mapped[str] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    date_of_birth: Mapped[date] = mapped_column(Date, index=True)
    sex: Mapped[str] = mapped_column(String(10))

    # Contact (phone stored normalized, email stored lower-case)
    phone: Mapped[str | None] = mapped_column(String(20), index=True)
    email: Mapped[str | None] = mapped_column(String(254), index=True)

    # Address
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state_province: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(100))

    # Emergency contact
    emergency_contact_name: Mapped[str | None] = mapped_column(String(200))
    emergency_contact_relationship: Mapped[str | None] = mapped_column(String(50))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(20))

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(10),
        index=True,
        default=PatientStatus.ACTIVE.value,
        server_default=text("'ACTIVE'"),
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivation_reason: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(r"patient_number ~ '^PAT-[0-9]{6,}$'", name="patient_number_format"),
        CheckConstraint("length(btrim(first_name)) > 0", name="first_name_not_blank"),
        CheckConstraint("length(btrim(last_name)) > 0", name="last_name_not_blank"),
        CheckConstraint("date_of_birth >= DATE '1900-01-01'", name="date_of_birth_min"),
        CheckConstraint(_in_list("sex", Sex), name="sex_valid"),
        CheckConstraint(_in_list("status", PatientStatus), name="status_valid"),
        CheckConstraint(
            "(status = 'ACTIVE' AND deactivated_at IS NULL AND deactivation_reason IS NULL)"
            " OR (status = 'INACTIVE' AND deactivated_at IS NOT NULL)",
            name="deactivation_consistent",
        ),
        CheckConstraint(
            "(emergency_contact_name IS NULL) = (emergency_contact_phone IS NULL)"
            " AND (emergency_contact_relationship IS NULL OR emergency_contact_name IS NOT NULL)",
            name="emergency_contact_complete",
        ),
    )


# Supports duplicate detection (case-insensitive name + date of birth) and name lookups.
Index(
    "ix_patients_lower_name_dob",
    func.lower(Patient.last_name),
    func.lower(Patient.first_name),
    Patient.date_of_birth,
)

# Patient identity uniqueness, enforced by PostgreSQL (the service checks first only to
# give a friendlier message): two patients may not share first + last name
# (case-insensitive) and date of birth AND the same phone, or the same email.
Index(
    "uq_patients_identity_phone",
    func.lower(Patient.last_name),
    func.lower(Patient.first_name),
    Patient.date_of_birth,
    Patient.phone,
    unique=True,
    postgresql_where=Patient.phone.is_not(None),
)
Index(
    "uq_patients_identity_email",
    func.lower(Patient.last_name),
    func.lower(Patient.first_name),
    Patient.date_of_birth,
    Patient.email,
    unique=True,
    postgresql_where=Patient.email.is_not(None),
)
