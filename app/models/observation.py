"""Observation: one measured or recorded value about a patient (Stage 2).

Generic by design (FHIR Observation-like, but relational): a `code` names what was
measured, the value is numeric (with a unit) or text, and `effective_at` is when it was
measured. Vital signs (temperature, heart rate, blood pressure, respiratory rate, SpO2,
weight, glucose, ...) are simply observations with well-known codes; see
app/services/observation_catalog.py.

Blood pressure is stored as two observations (systolic_blood_pressure and
diastolic_blood_pressure) sharing the same effective_at - the same shape Synthea
exports - which keeps every row a single scalar value.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Double, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.clinical_base import (
    CODE_LENGTH,
    CODE_SYSTEM_LENGTH,
    ClinicalRecordMixin,
    same_patient_encounter_fk,
)


class Observation(ClinicalRecordMixin, Base):
    __tablename__ = "observations"

    encounter_id: Mapped[uuid.UUID | None] = mapped_column()
    code: Mapped[str] = mapped_column(String(CODE_LENGTH))
    display: Mapped[str] = mapped_column(String(255))
    code_system: Mapped[str | None] = mapped_column(String(CODE_SYSTEM_LENGTH))
    system_code: Mapped[str | None] = mapped_column(String(CODE_LENGTH))
    value_numeric: Mapped[float | None] = mapped_column(Double)
    value_text: Mapped[str | None] = mapped_column(String(500))
    unit: Mapped[str | None] = mapped_column(String(32))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(1000))

    __table_args__ = (
        same_patient_encounter_fk(),
        CheckConstraint(r"code ~ '^[a-z][a-z0-9_]*$'", name="code_format"),
        CheckConstraint(
            "(value_numeric IS NULL) <> (value_text IS NULL)", name="exactly_one_value"
        ),
        CheckConstraint("value_text IS NULL OR unit IS NULL", name="unit_only_for_numeric"),
        CheckConstraint("(code_system IS NULL) = (system_code IS NULL)", name="coding_complete"),
        Index("ix_observations_patient_id_effective_at", "patient_id", "effective_at"),
        Index("ix_observations_patient_id_code", "patient_id", "code"),
        Index("ix_observations_encounter_id", "encounter_id"),
    )
