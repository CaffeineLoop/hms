"""Report: a generic, human-authored clinical report document (Stage 3).

One table for laboratory, imaging, consultation, discharge, procedure and other
reports (FHIR DiagnosticReport / Composition-like). A LABORATORY report may reference
the lab order whose results it reports.

Lifecycle:  DRAFT ──verify──> VERIFIED ──release──> RELEASED
              └────────cancel───────┴──> CANCELLED

Content is editable only while DRAFT. RELEASED and CANCELLED are terminal (amendments
are out of scope for Stage 3). People reference staff via *_staff_id (Stage 4); the text
columns keep a name snapshot, or legacy free text for older records.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

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


class ReportType(StrEnum):
    LABORATORY = "LABORATORY"
    IMAGING = "IMAGING"
    CONSULTATION = "CONSULTATION"
    DISCHARGE = "DISCHARGE"
    PROCEDURE = "PROCEDURE"
    OTHER = "OTHER"


class ReportStatus(StrEnum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


REPORT_TRANSITIONS: dict[ReportStatus, frozenset[ReportStatus]] = {
    ReportStatus.DRAFT: frozenset({ReportStatus.VERIFIED, ReportStatus.CANCELLED}),
    ReportStatus.VERIFIED: frozenset({ReportStatus.RELEASED, ReportStatus.CANCELLED}),
    ReportStatus.RELEASED: frozenset(),
    ReportStatus.CANCELLED: frozenset(),
}


class Report(ClinicalRecordMixin, Base):
    __tablename__ = "reports"

    encounter_id: Mapped[uuid.UUID | None] = mapped_column()
    lab_order_id: Mapped[uuid.UUID | None] = mapped_column()
    report_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(255))
    code_system: Mapped[str | None] = mapped_column(String(CODE_SYSTEM_LENGTH))
    code: Mapped[str | None] = mapped_column(String(CODE_LENGTH))
    status: Mapped[str] = mapped_column(String(20))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requested_by: Mapped[str | None] = mapped_column(String(200))
    requested_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    author_name: Mapped[str] = mapped_column(String(200))
    author_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())
    content: Mapped[str | None] = mapped_column(Text)
    conclusion: Mapped[str | None] = mapped_column(String(2000))
    verified_by: Mapped[str | None] = mapped_column(String(200))
    verified_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        same_patient_encounter_fk(),
        same_patient_fk("lab_order_id", "lab_orders"),
        CheckConstraint(in_list("report_type", ReportType), name="report_type_valid"),
        CheckConstraint(in_list("status", ReportStatus), name="status_valid"),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint("length(btrim(author_name)) > 0", name="author_name_not_blank"),
        CheckConstraint("(code_system IS NULL) = (code IS NULL)", name="coding_complete"),
        CheckConstraint("lab_order_id IS NULL OR report_type = 'LABORATORY'", name="lab_order_only_for_laboratory"),
        CheckConstraint(
            "status IN ('DRAFT', 'CANCELLED') OR (content IS NOT NULL AND length(btrim(content)) > 0)",
            name="content_required_after_draft",
        ),
        CheckConstraint(
            "(verified_at IS NULL) = (verified_by IS NULL)"
            " AND ((status IN ('VERIFIED', 'RELEASED')) = (verified_at IS NOT NULL) OR status = 'CANCELLED')",
            name="verification_matches_status",
        ),
        CheckConstraint("(status = 'RELEASED') = (released_at IS NOT NULL)", name="release_matches_status"),
        CheckConstraint(
            "(status = 'CANCELLED') = (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)",
            name="cancellation_matches_status",
        ),
        CheckConstraint("released_at IS NULL OR released_at >= verified_at", name="released_after_verified"),
        Index("ix_reports_patient_id_effective_at", "patient_id", "effective_at"),
        Index("ix_reports_encounter_id", "encounter_id"),
        Index("ix_reports_lab_order_id", "lab_order_id"),
    )
