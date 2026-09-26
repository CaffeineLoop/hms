"""Encounter: one contact between a patient and the facility (Stage 2).

Lifecycle (enforced by the service; the database enforces the timestamp consistency):

    PLANNED ──start──> IN_PROGRESS ──finish──> FINISHED
       │                    │
       └──────cancel────────┴──cancel──> CANCELLED

FINISHED and CANCELLED are terminal. Historical encounters (e.g. imported synthetic
data) may be created directly as FINISHED with both start and end timestamps.

attending_staff_id (Stage 4) optionally references the responsible clinician.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.clinical_base import ClinicalRecordMixin
from app.models.staff import staff_fk


class EncounterType(StrEnum):
    OPD = "OPD"
    EMERGENCY = "EMERGENCY"
    INPATIENT = "INPATIENT"
    FOLLOW_UP = "FOLLOW_UP"


class EncounterStatus(StrEnum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


# Allowed status changes; anything else is an invalid transition (HTTP 409).
ENCOUNTER_TRANSITIONS: dict[EncounterStatus, frozenset[EncounterStatus]] = {
    EncounterStatus.PLANNED: frozenset({EncounterStatus.IN_PROGRESS, EncounterStatus.CANCELLED}),
    EncounterStatus.IN_PROGRESS: frozenset({EncounterStatus.FINISHED, EncounterStatus.CANCELLED}),
    EncounterStatus.FINISHED: frozenset(),
    EncounterStatus.CANCELLED: frozenset(),
}

# Clinical records (observations, conditions, notes, ...) may only be attached to
# encounters that have actually taken place.
RECORDABLE_ENCOUNTER_STATUSES = frozenset({EncounterStatus.IN_PROGRESS, EncounterStatus.FINISHED})


def _in_list(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


class Encounter(ClinicalRecordMixin, Base):
    __tablename__ = "encounters"

    encounter_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(500))  # reason for visit / chief complaint
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    attending_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())  # Stage 4

    __table_args__ = (
        # Target of the composite (encounter_id, patient_id) foreign keys on clinical records.
        UniqueConstraint("id", "patient_id", name="uq_encounters_id_patient_id"),
        CheckConstraint(_in_list("encounter_type", EncounterType), name="encounter_type_valid"),
        CheckConstraint(_in_list("status", EncounterStatus), name="status_valid"),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        CheckConstraint("end_at IS NULL OR end_at >= start_at", name="end_after_start"),
        CheckConstraint(
            "(status = 'FINISHED') = (end_at IS NOT NULL) OR status = 'CANCELLED'",
            name="end_matches_status",
        ),
        CheckConstraint(
            "(status = 'CANCELLED') = (cancellation_reason IS NOT NULL)",
            name="cancellation_reason_matches_status",
        ),
        Index("ix_encounters_patient_id_start_at", "patient_id", "start_at"),
        Index("ix_encounters_status", "status"),
    )
