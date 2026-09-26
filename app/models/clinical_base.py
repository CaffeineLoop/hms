"""Building blocks shared by every clinical-record table (Stage 2 onwards).

Every clinical record:
- has an internal UUID primary key,
- belongs to exactly one patient (`patient_id` -> patients.id, ON DELETE RESTRICT),
- optionally/necessarily links to an encounter of THE SAME patient. That rule is enforced
  by PostgreSQL through a composite foreign key (encounter_id, patient_id) ->
  encounters (id, patient_id), not just by application code,
- carries `created_at` / `updated_at` system timestamps (timestamptz, set by the database),
  distinct from its clinical timestamp (when the thing actually happened).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, func, text
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

# Optional external coding (e.g. SNOMED CT for conditions, LOINC for observations,
# RxNorm for medication allergies) so Synthea/FHIR-derived data maps without loss.
CODE_SYSTEM_LENGTH = 100
CODE_LENGTH = 64


class ClinicalRecordMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )

    @declared_attr
    def patient_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(ForeignKey("patients.id", ondelete="RESTRICT"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def same_patient_encounter_fk() -> ForeignKeyConstraint:
    """(encounter_id, patient_id) must identify an encounter belonging to this row's patient.

    With the default MATCH SIMPLE semantics the constraint is skipped when encounter_id
    is NULL, so it also works for records that are not tied to an encounter.
    """
    return ForeignKeyConstraint(
        ["encounter_id", "patient_id"],
        ["encounters.id", "encounters.patient_id"],
        ondelete="RESTRICT",
    )


def same_patient_fk(column: str, table: str) -> ForeignKeyConstraint:
    """(column, patient_id) must identify a row of `table` belonging to this row's patient.

    Generalizes same_patient_encounter_fk for other parent records (e.g. lab orders).
    The target table needs a unique (id, patient_id) constraint.
    """
    return ForeignKeyConstraint(
        [column, "patient_id"], [f"{table}.id", f"{table}.patient_id"], ondelete="RESTRICT"
    )


def in_list(column: str, values: type[StrEnum]) -> str:
    """SQL for a CHECK that `column` holds one of the enum's values."""
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


def format_identifier(prefix: str, value: int, digits: int = 6) -> str:
    """('LAB-', 7) -> 'LAB-000007'. Larger values gain digits; they are never truncated."""
    if value < 1:
        raise ValueError("identifier sequence values start at 1")
    return f"{prefix}{value:0{digits}d}"
