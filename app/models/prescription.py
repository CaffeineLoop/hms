"""Prescriptions (Stage 3): a prescriber's medication order and its line items.

FHIR/Synthea mapping: each PrescriptionItem ~ MedicationRequest (medication code, e.g.
RxNorm, plus dosage instruction); the Prescription groups the items written together
during one encounter.

Lifecycle:
    DRAFT ──activate──> ACTIVE ──complete──> COMPLETED
                          │ ▲
                     hold │ │ resume
                          ▼ │
                        ON_HOLD
    DRAFT / ACTIVE / ON_HOLD ──cancel──> CANCELLED

Items can be added only while DRAFT; a prescription needs at least one item to be
activated. COMPLETED and CANCELLED are terminal. No dispensing or stock handling here
(pharmacy is a later workflow stage). The prescriber references staff via prescriber_staff_id
(Stage 4); prescriber_name keeps a snapshot, or legacy free text for older records.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.clinical_base import (
    CODE_LENGTH,
    CODE_SYSTEM_LENGTH,
    ClinicalRecordMixin,
    in_list,
    same_patient_encounter_fk,
)
from app.models.staff import staff_fk

PRESCRIPTION_PREFIX = "RX-"
prescription_number_seq = Sequence("prescription_number_seq", start=1, metadata=Base.metadata)


class PrescriptionStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


PRESCRIPTION_TRANSITIONS: dict[PrescriptionStatus, frozenset[PrescriptionStatus]] = {
    PrescriptionStatus.DRAFT: frozenset({PrescriptionStatus.ACTIVE, PrescriptionStatus.CANCELLED}),
    PrescriptionStatus.ACTIVE: frozenset(
        {PrescriptionStatus.ON_HOLD, PrescriptionStatus.COMPLETED, PrescriptionStatus.CANCELLED}
    ),
    PrescriptionStatus.ON_HOLD: frozenset({PrescriptionStatus.ACTIVE, PrescriptionStatus.CANCELLED}),
    PrescriptionStatus.COMPLETED: frozenset(),
    PrescriptionStatus.CANCELLED: frozenset(),
}


class Route(StrEnum):
    ORAL = "ORAL"
    SUBLINGUAL = "SUBLINGUAL"
    INTRAVENOUS = "INTRAVENOUS"
    INTRAMUSCULAR = "INTRAMUSCULAR"
    SUBCUTANEOUS = "SUBCUTANEOUS"
    INHALED = "INHALED"
    TOPICAL = "TOPICAL"
    TRANSDERMAL = "TRANSDERMAL"
    RECTAL = "RECTAL"
    VAGINAL = "VAGINAL"
    OPHTHALMIC = "OPHTHALMIC"
    OTIC = "OTIC"
    NASAL = "NASAL"
    OTHER = "OTHER"


class Frequency(StrEnum):
    ONCE = "ONCE"            # single dose
    STAT = "STAT"            # immediately, once
    OD = "OD"                # once daily
    BID = "BID"              # twice daily
    TID = "TID"              # three times daily
    QID = "QID"              # four times daily
    Q4H = "Q4H"
    Q6H = "Q6H"
    Q8H = "Q8H"
    Q12H = "Q12H"
    NOCTE = "NOCTE"          # at night
    WEEKLY = "WEEKLY"
    PRN = "PRN"              # as needed (see instructions for the condition/maximum)


class DurationUnit(StrEnum):
    DAYS = "DAYS"
    WEEKS = "WEEKS"
    MONTHS = "MONTHS"


class Prescription(ClinicalRecordMixin, Base):
    __tablename__ = "prescriptions"

    prescription_number: Mapped[str] = mapped_column(String(20), unique=True)
    encounter_id: Mapped[uuid.UUID] = mapped_column()
    prescriber_name: Mapped[str] = mapped_column(String(200))
    prescriber_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())
    status: Mapped[str] = mapped_column(String(20))
    prescribed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(String(2000))

    items: Mapped[list["PrescriptionItem"]] = relationship(
        back_populates="prescription", order_by="PrescriptionItem.line_number", lazy="selectin"
    )

    __table_args__ = (
        same_patient_encounter_fk(),
        CheckConstraint(r"prescription_number ~ '^RX-[0-9]{6,}$'", name="prescription_number_format"),
        CheckConstraint("length(btrim(prescriber_name)) > 0", name="prescriber_name_not_blank"),
        CheckConstraint(in_list("status", PrescriptionStatus), name="status_valid"),
        CheckConstraint(
            "(status = 'DRAFT') = (activated_at IS NULL) OR status = 'CANCELLED'", name="activation_matches_status"
        ),
        CheckConstraint("(status = 'COMPLETED') = (completed_at IS NOT NULL)", name="completion_matches_status"),
        CheckConstraint(
            "(status = 'CANCELLED') = (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)",
            name="cancellation_matches_status",
        ),
        CheckConstraint(
            "(activated_at IS NULL OR activated_at >= prescribed_at)"
            " AND (completed_at IS NULL OR completed_at >= activated_at)",
            name="timestamps_ordered",
        ),
        Index("ix_prescriptions_patient_id_prescribed_at", "patient_id", "prescribed_at"),
        Index("ix_prescriptions_encounter_id", "encounter_id"),
        Index("ix_prescriptions_status", "status"),
    )


class PrescriptionItem(Base):
    __tablename__ = "prescription_items"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    prescription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("prescriptions.id", ondelete="RESTRICT"))
    line_number: Mapped[int] = mapped_column(Integer)
    medicine_name: Mapped[str] = mapped_column(String(255))
    code_system: Mapped[str | None] = mapped_column(String(CODE_SYSTEM_LENGTH))
    code: Mapped[str | None] = mapped_column(String(CODE_LENGTH))
    dose_value: Mapped[float] = mapped_column(Double)
    dose_unit: Mapped[str] = mapped_column(String(32))
    route: Mapped[str] = mapped_column(String(20))
    frequency: Mapped[str] = mapped_column(String(10))
    duration_value: Mapped[int | None] = mapped_column(Integer)
    duration_unit: Mapped[str | None] = mapped_column(String(10))
    quantity: Mapped[float | None] = mapped_column(Double)
    quantity_unit: Mapped[str | None] = mapped_column(String(32))
    instructions: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    prescription: Mapped[Prescription] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("line_number >= 1", name="line_number_positive"),
        CheckConstraint("length(btrim(medicine_name)) > 0", name="medicine_name_not_blank"),
        CheckConstraint("(code_system IS NULL) = (code IS NULL)", name="coding_complete"),
        CheckConstraint("dose_value > 0", name="dose_positive"),
        CheckConstraint("length(btrim(dose_unit)) > 0", name="dose_unit_not_blank"),
        CheckConstraint(in_list("route", Route), name="route_valid"),
        CheckConstraint(in_list("frequency", Frequency), name="frequency_valid"),
        CheckConstraint(
            "(duration_value IS NULL) = (duration_unit IS NULL)"
            " AND (duration_value IS NULL OR duration_value > 0)"
            f" AND (duration_unit IS NULL OR {in_list('duration_unit', DurationUnit)})",
            name="duration_valid",
        ),
        CheckConstraint(
            "(quantity IS NULL OR quantity > 0) AND (quantity_unit IS NULL OR quantity IS NOT NULL)",
            name="quantity_valid",
        ),
        UniqueConstraint("prescription_id", "line_number", name="uq_prescription_items_prescription_id_line_number"),
        Index("ix_prescription_items_prescription_id", "prescription_id"),
    )
