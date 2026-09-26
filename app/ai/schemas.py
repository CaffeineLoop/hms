"""AI contracts (Stage 7).

Three layers, deliberately separate from diagnosis/prescription/clinical-record entities:
- AIAnalysisRequest  what the clinician asks (validated API input);
- ModelAnalysisOutput what the LLM must return (validated before anything is shown);
- AIAnalysisResult   what the API returns (status + validated output + provenance).
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


class AnalysisType(StrEnum):
    CLINICAL_SUMMARY = "CLINICAL_SUMMARY"
    VITALS_REVIEW = "VITALS_REVIEW"
    MEDICATION_REVIEW = "MEDICATION_REVIEW"
    LAB_REVIEW = "LAB_REVIEW"
    QUESTION = "QUESTION"


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

    @model_validator(mode="after")
    def _question_for_questions(self) -> "AIAnalysisRequest":
        if self.analysis_type == AnalysisType.QUESTION and not self.question:
            raise ValueError("question is required for QUESTION analyses")
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
    output: ModelAnalysisOutput | None = None
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
