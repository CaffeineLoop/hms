"""AI contracts (Stages 7-8).

Three layers, deliberately separate from diagnosis/prescription/clinical-record entities:
- AIAnalysisRequest  what the clinician asks (validated API input);
- ModelAnalysisOutput what the LLM must return (validated before anything is shown);
  ModelRiskOutput    the FOUR_DAY_RISK variant (Stage 8), validated structurally here and
                     semantically in guardrails.check_risk_output;
- AIAnalysisResult   what the API returns (status + validated output + provenance).
Stage 8 adds the AI review pathway contracts (RiskAnalysisRead / RiskReviewCreate): a stored
risk analysis is an AI suggestion awaiting human review, never a clinical record.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.ai.risk_signals import ANALYSIS_HORIZON, ANALYSIS_HORIZON_DAYS, ReviewPriority, SignalCategory
from app.core.clock import latest_allowed_instant
from app.schemas.common import PageParams


class AnalysisType(StrEnum):
    CLINICAL_SUMMARY = "CLINICAL_SUMMARY"
    VITALS_REVIEW = "VITALS_REVIEW"
    MEDICATION_REVIEW = "MEDICATION_REVIEW"
    LAB_REVIEW = "LAB_REVIEW"
    QUESTION = "QUESTION"
    FOUR_DAY_RISK = "FOUR_DAY_RISK"  # Stage 8: potential risk signals for the next 4 days


class AnalysisStatus(StrEnum):
    COMPLETED = "COMPLETED"  # validated analysis returned
    ABSTAINED = "ABSTAINED"  # the assistant declined to answer (missing data, unsafe/invalid output)
    REFUSED = "REFUSED"      # the request itself is outside the assistant's boundary


Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class AIAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: uuid.UUID
    analysis_type: AnalysisType
    question: Question | None = Field(default=None, description="Required for QUESTION; optional focus otherwise")
    tools: list[Annotated[str, StringConstraints(max_length=64)]] | None = Field(
        default=None, max_length=20,
        description="Optionally restrict evidence to these read-only tools (names from GET /api/ai/capabilities)",
    )
    reference_at: AwareDatetime | None = Field(
        default=None,
        description="FOUR_DAY_RISK only: the clinical reference time (default: now). Not in the future. "
                    "The horizon is always reference_at .. reference_at + 4 days.",
    )
    analysis_horizon_days: Literal[4] | None = Field(
        default=None, description="FOUR_DAY_RISK only: fixed at 4; any other value is rejected")

    @field_validator("reference_at")
    @classmethod
    def _reference_not_future(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value > latest_allowed_instant():
            raise ValueError("reference_at cannot be in the future")
        return value.astimezone(UTC).replace(microsecond=0)

    @model_validator(mode="after")
    def _question_for_questions(self) -> "AIAnalysisRequest":
        if self.analysis_type == AnalysisType.QUESTION and not self.question:
            raise ValueError("question is required for QUESTION analyses")
        if self.analysis_type != AnalysisType.FOUR_DAY_RISK and (
                self.reference_at is not None or self.analysis_horizon_days is not None):
            raise ValueError("reference_at / analysis_horizon_days apply to FOUR_DAY_RISK analyses only")
        return self


class EvidenceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: Annotated[str, StringConstraints(max_length=100)]
    relevance: Annotated[str, StringConstraints(max_length=300)]


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ModelAnalysisOutput(BaseModel):
    """The only shape accepted from the LLM. Anything else is discarded (the assistant abstains)."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ANALYSIS", "ABSTAIN"]
    analysis_type: AnalysisType
    patient_reference: Annotated[str, StringConstraints(max_length=20)]
    analysis: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
    evidence: list[EvidenceCitation] = Field(default_factory=list, max_length=40)
    limitations: list[ShortText] = Field(min_length=1, max_length=10)
    review_suggestions: list[ShortText] = Field(default_factory=list, max_length=8)
    requires_human_review: bool
    abstain_reason: Annotated[str, StringConstraints(max_length=500)] | None = None

    @model_validator(mode="after")
    def _consistency(self) -> "ModelAnalysisOutput":
        if self.status == "ANALYSIS":
            if not self.analysis:
                raise ValueError("analysis text is required")
            if not self.evidence:
                raise ValueError("an analysis must cite at least one evidence source")
        elif not self.abstain_reason:
            raise ValueError("abstain_reason is required when abstaining")
        return self

    @field_validator("requires_human_review")
    @classmethod
    def _always_review(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("requires_human_review must be true")
        return value


# --- Stage 8: four-day potential risk analysis ------------------------------------------------

SourceId = Annotated[str, StringConstraints(max_length=100)]
SignalId = Annotated[str, StringConstraints(pattern=r"^SIG-\d{2}$")]


class ModelRiskSignal(BaseModel):
    """The model's explanation of ONE deterministic signal. It cannot add, drop or re-grade signals."""

    model_config = ConfigDict(extra="forbid")

    signal_id: SignalId
    category: SignalCategory
    priority: ReviewPriority
    explanation: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
    evidence: list[SourceId] = Field(min_length=1, max_length=20)


class ModelObservedTrend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: ShortText
    evidence: list[SourceId] = Field(min_length=1, max_length=20)


class ModelRiskOutput(BaseModel):
    """The only shape accepted from the LLM for FOUR_DAY_RISK."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ANALYSIS", "ABSTAIN"]
    analysis_type: Literal[AnalysisType.FOUR_DAY_RISK]
    patient_reference: Annotated[str, StringConstraints(max_length=20)]
    reference_at: AwareDatetime
    horizon_start: AwareDatetime
    horizon_end: AwareDatetime
    analysis_horizon_days: Literal[4]
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
    risk_signals: list[ModelRiskSignal] = Field(default_factory=list, max_length=30)
    observed_trends: list[ModelObservedTrend] = Field(default_factory=list, max_length=10)
    evidence: list[EvidenceCitation] = Field(default_factory=list, max_length=40)
    limitations: list[ShortText] = Field(min_length=1, max_length=10)
    precautionary_suggestions: list[ShortText] = Field(default_factory=list, max_length=8)
    requires_human_review: bool
    abstain_reason: Annotated[str, StringConstraints(max_length=500)] | None = None

    @field_validator("requires_human_review")
    @classmethod
    def _always_review(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("requires_human_review must be true")
        return value

    @model_validator(mode="after")
    def _consistency(self) -> "ModelRiskOutput":
        if self.horizon_start != self.reference_at:
            raise ValueError("horizon_start must equal reference_at")
        if self.horizon_end - self.horizon_start != ANALYSIS_HORIZON:
            raise ValueError(f"the horizon must be exactly {ANALYSIS_HORIZON_DAYS} days")
        if len({s.signal_id for s in self.risk_signals}) != len(self.risk_signals):
            raise ValueError("signal_id values must be unique")
        if self.status == "ANALYSIS":
            if not self.summary:
                raise ValueError("summary is required")
            if not self.evidence:
                raise ValueError("an analysis must cite at least one evidence source")
        elif not self.abstain_reason:
            raise ValueError("abstain_reason is required when abstaining")
        return self


class RiskEngineInfo(BaseModel):
    ruleset_id: str
    version: str
    validated: bool = Field(description="False: prototype thresholds, not clinically validated")
    notice: str


class RiskSignalRead(BaseModel):
    signal_id: str
    rule_id: str
    category: SignalCategory
    priority: ReviewPriority = Field(description="Suggested priority for clinical review (not a severity score)")
    title: str
    detail: str
    evidence: list[str]


class RiskReviewStatus(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"


class RiskTrigger(StrEnum):
    MANUAL = "MANUAL"
    EVENT = "EVENT"


class RiskContext(BaseModel):
    reference_at: datetime
    horizon_start: datetime
    horizon_end: datetime
    analysis_horizon_days: Literal[4] = ANALYSIS_HORIZON_DAYS
    evidence_window_start: datetime
    evidence_window_end: datetime
    engine: RiskEngineInfo
    signals: list[RiskSignalRead] = Field(description="Deterministic signals (authoritative; the model only explains)")
    data_gaps: list[str]
    max_priority: ReviewPriority | None
    trigger: RiskTrigger
    risk_analysis_id: uuid.UUID | None = Field(default=None, description="Stored for human review (AI review pathway)")
    review_status: RiskReviewStatus | None = None


class AIModelInfo(BaseModel):
    provider: str
    model: str


class AIAnalysisResult(BaseModel):
    request_id: str
    status: AnalysisStatus
    reason_code: str | None = None
    message: str
    patient_id: uuid.UUID
    patient_number: str | None = None
    analysis_type: AnalysisType
    output: ModelAnalysisOutput | ModelRiskOutput | None = None
    risk: RiskContext | None = Field(default=None, description="FOUR_DAY_RISK only")
    tools_used: list[str]
    tools_withheld: list[str] = Field(description="Tools skipped because the caller lacks their permission")
    evidence_count: int
    model: AIModelInfo | None = None
    generated_at: datetime
    disclaimer: str = (
        "AI-generated, read-only clinical analysis to support - not replace - clinical judgement. "
        "It is not a diagnosis, prescription or order and must be reviewed by a qualified clinician."
    )


class AIToolInfo(BaseModel):
    name: str
    description: str
    required_permission: str
    read_only: bool
    available_to_you: bool


class AICapabilities(BaseModel):
    enabled: bool
    provider: str
    model: str
    analysis_types: list[AnalysisType]
    tools: list[AIToolInfo]


# --- Stage 8: AI review pathway ---------------------------------------------------------------


class RiskAnalysisRead(BaseModel):
    """A stored four-day risk analysis: an AI suggestion awaiting human review. Not a clinical record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    status: AnalysisStatus
    reason_code: str | None
    trigger: RiskTrigger
    trigger_event: str | None
    trigger_source_id: uuid.UUID | None
    requested_by_user_id: uuid.UUID
    requested_by_staff_id: uuid.UUID
    reference_at: datetime
    horizon_start: datetime
    horizon_end: datetime
    analysis_horizon_days: int
    ruleset_id: str
    ruleset_version: str
    ruleset_validated: bool
    signals: list[RiskSignalRead]
    data_gaps: list[str]
    max_priority: ReviewPriority | None
    output: ModelRiskOutput | None
    provider: str
    model: str
    requires_human_review: bool
    review_status: RiskReviewStatus
    reviewed_by_user_id: uuid.UUID | None
    reviewed_by_staff_id: uuid.UUID | None
    reviewed_at: datetime | None
    review_comment: str | None
    created_at: datetime
    disclaimer: str = (
        "AI-generated potential risk signals for clinical review only. Not a diagnosis, prediction, "
        "order or treatment decision; the demonstration signal rules are not clinically validated."
    )


class RiskReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal[RiskReviewStatus.ACKNOWLEDGED, RiskReviewStatus.DISMISSED]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None


class RiskAnalysisListParams(PageParams):
    patient_id: uuid.UUID | None = None
    review_status: RiskReviewStatus | None = None
