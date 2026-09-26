"""Condition: a documented clinical problem or diagnosis (Stage 2).

These are clinician-documented records, never AI-generated. `recorded_at` is when it
was documented; `onset_at` / `resolved_at` are the clinical dates when known.
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
    same_patient_encounter_fk,
)


class ConditionStatus(StrEnum):
    SUSPECTED = "SUSPECTED"
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    HISTORICAL = "HISTORICAL"


CONDITION_TRANSITIONS: dict[ConditionStatus, frozenset[ConditionStatus]] = {
    ConditionStatus.SUSPECTED: frozenset({ConditionStatus.ACTIVE, ConditionStatus.RESOLVED}),
    ConditionStatus.ACTIVE: frozenset({ConditionStatus.RESOLVED}),
    ConditionStatus.RESOLVED: frozenset({ConditionStatus.ACTIVE}),  # recurrence
    ConditionStatus.HISTORICAL: frozenset({ConditionStatus.ACTIVE}),
}


class Condition(ClinicalRecordMixin, Base):
    __tablename__ = "conditions"

    encounter_id: Mapped[uuid.UUID | None] = mapped_column()
    name: Mapped[str] = mapped_column(String(255))
    code_system: Mapped[str | None] = mapped_column(String(CODE_SYSTEM_LENGTH))
    code: Mapped[str | None] = mapped_column(String(CODE_LENGTH))
    status: Mapped[str] = mapped_column(String(20))
    onset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        same_patient_encounter_fk(),
        CheckConstraint(
            "status IN ('SUSPECTED', 'ACTIVE', 'RESOLVED', 'HISTORICAL')", name="status_valid"
        ),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint(
            "resolved_at IS NULL OR onset_at IS NULL OR resolved_at >= onset_at",
            name="resolved_after_onset",
        ),
        CheckConstraint("(code_system IS NULL) = (code IS NULL)", name="coding_complete"),
        Index("ix_conditions_patient_id_recorded_at", "patient_id", "recorded_at"),
        Index("ix_conditions_encounter_id", "encounter_id"),
    )
