"""Clinical note: human-authored documentation written during an encounter (Stage 2).

Notes are append-only: there is no update endpoint. A correction or addendum is a new
note. No AI-generated notes.

Author: `author_staff_id` references the staff member (Stage 4); `author_name` keeps a
snapshot of their name, or the free-text author of records created before Stage 4.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.clinical_base import ClinicalRecordMixin, same_patient_encounter_fk
from app.models.staff import staff_fk


class NoteType(StrEnum):
    PROGRESS = "PROGRESS"
    HISTORY_AND_PHYSICAL = "HISTORY_AND_PHYSICAL"
    CONSULTATION = "CONSULTATION"
    NURSING = "NURSING"
    PROCEDURE = "PROCEDURE"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    OTHER = "OTHER"


class ClinicalNote(ClinicalRecordMixin, Base):
    __tablename__ = "clinical_notes"

    encounter_id: Mapped[uuid.UUID] = mapped_column()
    note_type: Mapped[str] = mapped_column(String(30))
    author_name: Mapped[str] = mapped_column(String(200))  # name snapshot / legacy free text
    author_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())  # Stage 4
    content: Mapped[str] = mapped_column(Text)
    authored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        same_patient_encounter_fk(),
        CheckConstraint(
            "note_type IN ('PROGRESS', 'HISTORY_AND_PHYSICAL', 'CONSULTATION', 'NURSING',"
            " 'PROCEDURE', 'DISCHARGE_SUMMARY', 'OTHER')",
            name="note_type_valid",
        ),
        CheckConstraint("length(btrim(author_name)) > 0", name="author_name_not_blank"),
        CheckConstraint("length(btrim(content)) > 0", name="content_not_blank"),
        Index("ix_clinical_notes_patient_id_authored_at", "patient_id", "authored_at"),
        Index("ix_clinical_notes_encounter_id", "encounter_id"),
    )
