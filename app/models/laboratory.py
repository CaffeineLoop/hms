"""Laboratory: orders, samples and results (Stage 3).

Lifecycle of a LabOrder (enforced by the service; timestamp/metadata consistency is
also enforced by PostgreSQL CHECK constraints):

    ORDERED ─collect sample─> SAMPLE_COLLECTED ─start─> PROCESSING ─enter results─> RESULT_ENTERED
                                                                                         │ verify
                                                                RELEASED <─release── VERIFIED

    ORDERED / SAMPLE_COLLECTED / PROCESSING / RESULT_ENTERED ──cancel──> CANCELLED

RELEASED and CANCELLED are terminal. Results can be entered or corrected only while the
order is PROCESSING / RESULT_ENTERED; once VERIFIED they are locked.

Mapping to FHIR/Synthea: LabOrder ~ ServiceRequest (+ DiagnosticReport grouping),
LabSample ~ Specimen, LabResult ~ laboratory Observation (LOINC-coded).
People (orderer, collector, technician, verifier) reference staff via *_staff_id (Stage 4);
the text columns keep a name snapshot, or legacy free text for older records.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Double,
    Index,
    Sequence,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.clinical_base import (
    CODE_LENGTH,
    CODE_SYSTEM_LENGTH,
    ClinicalRecordMixin,
    in_list,
    same_patient_encounter_fk,
    same_patient_fk,
)
from app.models.staff import staff_fk

LAB_ORDER_PREFIX = "LAB-"
LAB_SAMPLE_PREFIX = "SMP-"
lab_order_number_seq = Sequence("lab_order_number_seq", start=1, metadata=Base.metadata)
lab_sample_accession_seq = Sequence("lab_sample_accession_seq", start=1, metadata=Base.metadata)


class LabOrderStatus(StrEnum):
    ORDERED = "ORDERED"
    SAMPLE_COLLECTED = "SAMPLE_COLLECTED"
    PROCESSING = "PROCESSING"
    RESULT_ENTERED = "RESULT_ENTERED"
    VERIFIED = "VERIFIED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class LabPriority(StrEnum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    STAT = "STAT"


class SpecimenType(StrEnum):
    BLOOD = "BLOOD"
    SERUM = "SERUM"
    PLASMA = "PLASMA"
    URINE = "URINE"
    STOOL = "STOOL"
    SPUTUM = "SPUTUM"
    CSF = "CSF"
    SWAB = "SWAB"
    TISSUE = "TISSUE"
    OTHER = "OTHER"


class ResultInterpretation(StrEnum):
    NORMAL = "NORMAL"
    LOW = "LOW"
    HIGH = "HIGH"
    CRITICAL_LOW = "CRITICAL_LOW"
    CRITICAL_HIGH = "CRITICAL_HIGH"
    ABNORMAL = "ABNORMAL"


LAB_ORDER_TRANSITIONS: dict[LabOrderStatus, frozenset[LabOrderStatus]] = {
    LabOrderStatus.ORDERED: frozenset({LabOrderStatus.SAMPLE_COLLECTED, LabOrderStatus.CANCELLED}),
    LabOrderStatus.SAMPLE_COLLECTED: frozenset({LabOrderStatus.PROCESSING, LabOrderStatus.CANCELLED}),
    LabOrderStatus.PROCESSING: frozenset({LabOrderStatus.RESULT_ENTERED, LabOrderStatus.CANCELLED}),
    LabOrderStatus.RESULT_ENTERED: frozenset({LabOrderStatus.VERIFIED, LabOrderStatus.CANCELLED}),
    LabOrderStatus.VERIFIED: frozenset({LabOrderStatus.RELEASED}),
    LabOrderStatus.RELEASED: frozenset(),
    LabOrderStatus.CANCELLED: frozenset(),
}

# Order states in which samples may be (additionally) collected / results entered or corrected.
SAMPLE_COLLECTION_STATUSES = frozenset(
    {LabOrderStatus.ORDERED, LabOrderStatus.SAMPLE_COLLECTED, LabOrderStatus.PROCESSING}
)
RESULT_ENTRY_STATUSES = frozenset({LabOrderStatus.PROCESSING, LabOrderStatus.RESULT_ENTERED})


class LabOrder(ClinicalRecordMixin, Base):
    __tablename__ = "lab_orders"

    order_number: Mapped[str] = mapped_column(String(20), unique=True)
    encounter_id: Mapped[uuid.UUID] = mapped_column()
    test_code: Mapped[str] = mapped_column(String(CODE_LENGTH))
    test_name: Mapped[str] = mapped_column(String(255))
    code_system: Mapped[str | None] = mapped_column(String(CODE_SYSTEM_LENGTH))
    system_code: Mapped[str | None] = mapped_column(String(CODE_LENGTH))
    priority: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20))
    clinical_indication: Mapped[str | None] = mapped_column(String(500))
    ordered_by: Mapped[str] = mapped_column(String(200))
    ordered_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    results_entered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[str | None] = mapped_column(String(200))
    verified_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))

    # Read-only views: the service sets lab_order_id/patient_id explicitly (the composite
    # foreign key shares patient_id, which the ORM must not try to manage).
    samples: Mapped[list["LabSample"]] = relationship(
        primaryjoin="LabOrder.id == foreign(LabSample.lab_order_id)",
        order_by="(LabSample.collected_at, LabSample.accession_number)",
        lazy="selectin",
        viewonly=True,
    )
    results: Mapped[list["LabResult"]] = relationship(
        primaryjoin="LabOrder.id == foreign(LabResult.lab_order_id)",
        order_by="LabResult.analyte_code",
        lazy="selectin",
        viewonly=True,
    )

    __table_args__ = (
        UniqueConstraint("id", "patient_id", name="uq_lab_orders_id_patient_id"),
        same_patient_encounter_fk(),
        CheckConstraint(r"order_number ~ '^LAB-[0-9]{6,}$'", name="order_number_format"),
        CheckConstraint(r"test_code ~ '^[a-z][a-z0-9_]*$'", name="test_code_format"),
        CheckConstraint("length(btrim(test_name)) > 0", name="test_name_not_blank"),
        CheckConstraint("length(btrim(ordered_by)) > 0", name="ordered_by_not_blank"),
        CheckConstraint("(code_system IS NULL) = (system_code IS NULL)", name="coding_complete"),
        CheckConstraint(in_list("priority", LabPriority), name="priority_valid"),
        CheckConstraint(in_list("status", LabOrderStatus), name="status_valid"),
        CheckConstraint(
            "(verified_at IS NULL) = (verified_by IS NULL)"
            " AND ((status IN ('VERIFIED', 'RELEASED')) = (verified_at IS NOT NULL))",
            name="verification_matches_status",
        ),
        CheckConstraint("(status = 'RELEASED') = (released_at IS NOT NULL)", name="release_matches_status"),
        CheckConstraint(
            "(status = 'CANCELLED') = (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)",
            name="cancellation_matches_status",
        ),
        CheckConstraint(
            "(processing_started_at IS NULL OR processing_started_at >= ordered_at)"
            " AND (verified_at IS NULL OR verified_at >= ordered_at)"
            " AND (released_at IS NULL OR released_at >= verified_at)",
            name="timestamps_ordered",
        ),
        Index("ix_lab_orders_patient_id_ordered_at", "patient_id", "ordered_at"),
        Index("ix_lab_orders_encounter_id", "encounter_id"),
        Index("ix_lab_orders_status", "status"),
    )


class LabSample(ClinicalRecordMixin, Base):
    __tablename__ = "lab_samples"

    accession_number: Mapped[str] = mapped_column(String(20), unique=True)
    lab_order_id: Mapped[uuid.UUID] = mapped_column()
    specimen_type: Mapped[str] = mapped_column(String(20))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    collected_by: Mapped[str] = mapped_column(String(200))
    collected_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())
    notes: Mapped[str | None] = mapped_column(String(1000))

    lab_order: Mapped[LabOrder] = relationship(
        primaryjoin="LabOrder.id == foreign(LabSample.lab_order_id)", viewonly=True
    )

    __table_args__ = (
        same_patient_fk("lab_order_id", "lab_orders"),
        CheckConstraint(r"accession_number ~ '^SMP-[0-9]{6,}$'", name="accession_number_format"),
        CheckConstraint(in_list("specimen_type", SpecimenType), name="specimen_type_valid"),
        CheckConstraint("length(btrim(collected_by)) > 0", name="collected_by_not_blank"),
        Index("ix_lab_samples_lab_order_id", "lab_order_id"),
        Index("ix_lab_samples_patient_id_collected_at", "patient_id", "collected_at"),
    )


class LabResult(ClinicalRecordMixin, Base):
    __tablename__ = "lab_results"

    lab_order_id: Mapped[uuid.UUID] = mapped_column()
    analyte_code: Mapped[str] = mapped_column(String(CODE_LENGTH))
    analyte_name: Mapped[str] = mapped_column(String(255))
    code_system: Mapped[str | None] = mapped_column(String(CODE_SYSTEM_LENGTH))
    system_code: Mapped[str | None] = mapped_column(String(CODE_LENGTH))
    value_numeric: Mapped[float | None] = mapped_column(Double)
    value_text: Mapped[str | None] = mapped_column(String(500))
    unit: Mapped[str | None] = mapped_column(String(32))
    reference_low: Mapped[float | None] = mapped_column(Double)
    reference_high: Mapped[float | None] = mapped_column(Double)
    reference_text: Mapped[str | None] = mapped_column(String(100))
    interpretation: Mapped[str | None] = mapped_column(String(20))
    resulted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entered_by: Mapped[str] = mapped_column(String(200))
    entered_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())
    notes: Mapped[str | None] = mapped_column(String(1000))

    lab_order: Mapped[LabOrder] = relationship(
        primaryjoin="LabOrder.id == foreign(LabResult.lab_order_id)", viewonly=True
    )

    __table_args__ = (
        same_patient_fk("lab_order_id", "lab_orders"),
        UniqueConstraint("lab_order_id", "analyte_code", name="uq_lab_results_lab_order_id_analyte_code"),
        CheckConstraint(r"analyte_code ~ '^[a-z][a-z0-9_]*$'", name="analyte_code_format"),
        CheckConstraint("length(btrim(analyte_name)) > 0", name="analyte_name_not_blank"),
        CheckConstraint("length(btrim(entered_by)) > 0", name="entered_by_not_blank"),
        CheckConstraint("(value_numeric IS NULL) <> (value_text IS NULL)", name="exactly_one_value"),
        CheckConstraint("value_text IS NULL OR unit IS NULL", name="unit_only_for_numeric"),
        CheckConstraint(
            "(reference_low IS NULL AND reference_high IS NULL) OR value_numeric IS NOT NULL",
            name="numeric_range_only_for_numeric",
        ),
        CheckConstraint(
            "reference_low IS NULL OR reference_high IS NULL OR reference_low <= reference_high",
            name="reference_range_ordered",
        ),
        CheckConstraint("(code_system IS NULL) = (system_code IS NULL)", name="coding_complete"),
        CheckConstraint(
            f"interpretation IS NULL OR {in_list('interpretation', ResultInterpretation)}",
            name="interpretation_valid",
        ),
        Index("ix_lab_results_patient_id_resulted_at", "patient_id", "resulted_at"),
    )
