"""Allergy / intolerance: a documented adverse reaction risk to a substance (Stage 2).

A patient can have at most one ACTIVE allergy record per substance (case-insensitive),
enforced by a partial unique index.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.clinical_base import (
    CODE_LENGTH,
    CODE_SYSTEM_LENGTH,
    ClinicalRecordMixin,
    same_patient_encounter_fk,
)


class AllergyCategory(StrEnum):
    FOOD = "FOOD"
    MEDICATION = "MEDICATION"
    ENVIRONMENT = "ENVIRONMENT"
    BIOLOGIC = "BIOLOGIC"


class AllergySeverity(StrEnum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class AllergyStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    RESOLVED = "RESOLVED"


ALLERGY_TRANSITIONS: dict[AllergyStatus, frozenset[AllergyStatus]] = {
    AllergyStatus.ACTIVE: frozenset({AllergyStatus.INACTIVE, AllergyStatus.RESOLVED}),
    AllergyStatus.INACTIVE: frozenset({AllergyStatus.ACTIVE, AllergyStatus.RESOLVED}),
    AllergyStatus.RESOLVED: frozenset({AllergyStatus.ACTIVE}),
}


class Allergy(ClinicalRecordMixin, Base):
    __tablename__ = "allergies"

    encounter_id: Mapped[uuid.UUID | None] = mapped_column()
    substance: Mapped[str] = mapped_column(String(255))
    code_system: Mapped[str | None] = mapped_column(String(CODE_SYSTEM_LENGTH))
    code: Mapped[str | None] = mapped_column(String(CODE_LENGTH))
    category: Mapped[str | None] = mapped_column(String(20))
    reaction: Mapped[str | None] = mapped_column(String(500))
    severity: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10))
    onset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        same_patient_encounter_fk(),
        CheckConstraint("length(btrim(substance)) > 0", name="substance_not_blank"),
        CheckConstraint(
            "category IS NULL OR category IN ('FOOD', 'MEDICATION', 'ENVIRONMENT', 'BIOLOGIC')",
            name="category_valid",
        ),
        CheckConstraint(
            "severity IS NULL OR severity IN ('MILD', 'MODERATE', 'SEVERE')", name="severity_valid"
        ),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'RESOLVED')", name="status_valid"),
        CheckConstraint("(code_system IS NULL) = (code IS NULL)", name="coding_complete"),
        Index("ix_allergies_patient_id_recorded_at", "patient_id", "recorded_at"),
    )


Index(
    "uq_allergies_active_substance",
    Allergy.patient_id,
    func.lower(Allergy.substance),
    unique=True,
    postgresql_where=Allergy.status == "ACTIVE",
)
