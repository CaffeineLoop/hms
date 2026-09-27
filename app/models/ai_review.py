"""Stored four-day risk analyses awaiting human review - the AI review pathway (Stage 8).

An `AIRiskAnalysis` is an AI SUGGESTION, deliberately separate from every clinical entity: it is
not a diagnosis, condition, order, prescription or note, it never changes one, and nothing in
the clinical model references it. It keeps:
- the deterministic signals (authoritative; also kept when the model's answer was rejected),
- the validated model output (or NULL when the assistant abstained),
- the fixed horizon (reference_at .. reference_at + 4 days, enforced by CHECK constraints),
- the rule set identity and its `validated` flag, and
- the human review (PENDING_REVIEW -> ACKNOWLEDGED | DISMISSED, once, by a staff-linked user).

A trigger (migration 0010) makes the analysis content immutable: an UPDATE may only record the
review, and only while the analysis is still PENDING_REVIEW.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.ai.risk_signals import ANALYSIS_HORIZON_DAYS, ReviewPriority
from app.ai.schemas import AnalysisStatus, RiskReviewStatus, RiskTrigger
from app.db.base import Base
from app.models.clinical_base import in_list
from app.models.staff import staff_fk

STORED_STATUSES = (AnalysisStatus.COMPLETED, AnalysisStatus.ABSTAINED)


def _user_fk() -> ForeignKey:
    return ForeignKey("users.id", ondelete="RESTRICT")


class AIRiskAnalysis(Base):
    __tablename__ = "ai_risk_analyses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4,
                                          server_default=text("gen_random_uuid()"))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(10))
    reason_code: Mapped[str | None] = mapped_column(String(50))
    trigger: Mapped[str] = mapped_column(String(10))
    trigger_event: Mapped[str | None] = mapped_column(String(50))
    trigger_source_id: Mapped[uuid.UUID | None] = mapped_column()
    request_id: Mapped[str | None] = mapped_column(String(64))
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    requested_by_staff_id: Mapped[uuid.UUID] = mapped_column(staff_fk())
    reference_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    horizon_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    horizon_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    analysis_horizon_days: Mapped[int] = mapped_column(SmallInteger, server_default=text(str(ANALYSIS_HORIZON_DAYS)))
    ruleset_id: Mapped[str] = mapped_column(String(50))
    ruleset_version: Mapped[str] = mapped_column(String(20))
    ruleset_validated: Mapped[bool] = mapped_column(Boolean)
    signals: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    data_gaps: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    max_priority: Mapped[str | None] = mapped_column(String(10))
    output: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))  # None -> SQL NULL
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(100))
    requires_human_review: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    review_status: Mapped[str] = mapped_column(String(20), server_default=text("'PENDING_REVIEW'"))
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    reviewed_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(staff_fk())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('COMPLETED', 'ABSTAINED')", name="status_valid"),
        CheckConstraint(in_list("trigger", RiskTrigger), name="trigger_valid"),
        CheckConstraint("(trigger = 'EVENT') = (trigger_event IS NOT NULL)", name="trigger_event_matches"),
        CheckConstraint(f"analysis_horizon_days = {ANALYSIS_HORIZON_DAYS}", name="horizon_is_four_days"),
        CheckConstraint("horizon_start = reference_at", name="horizon_starts_at_reference"),
        CheckConstraint(f"horizon_end = horizon_start + interval '{ANALYSIS_HORIZON_DAYS} days'",
                        name="horizon_end_matches"),
        CheckConstraint("jsonb_typeof(signals) = 'array'", name="signals_is_array"),
        CheckConstraint("jsonb_typeof(data_gaps) = 'array'", name="data_gaps_is_array"),
        CheckConstraint("output IS NULL OR jsonb_typeof(output) = 'object'", name="output_is_object"),
        CheckConstraint(f"max_priority IS NULL OR {in_list('max_priority', ReviewPriority)}",
                        name="max_priority_valid"),
        CheckConstraint("requires_human_review", name="requires_human_review"),
        CheckConstraint(in_list("review_status", RiskReviewStatus), name="review_status_valid"),
        CheckConstraint(
            "(review_status = 'PENDING_REVIEW') = (reviewed_at IS NULL) "
            "AND (reviewed_at IS NULL) = (reviewed_by_user_id IS NULL) "
            "AND (reviewed_at IS NULL) = (reviewed_by_staff_id IS NULL) "
            "AND (review_comment IS NULL OR reviewed_at IS NOT NULL)",
            name="review_consistent",
        ),
        Index("ix_ai_risk_analyses_patient_id_created_at", "patient_id", "created_at"),
        Index("ix_ai_risk_analyses_review_status_created_at", "review_status", "created_at"),
        Index("ix_ai_risk_analyses_patient_trigger_created_at", "patient_id", "trigger", "created_at"),
    )
