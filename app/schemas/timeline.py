"""API contract for GET /api/patients/{patient_id}/timeline."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import AnyClinicalTimestamp, PageParams


class TimelineEventType(StrEnum):
    ENCOUNTER = "encounter"
    OBSERVATION = "observation"
    CONDITION = "condition"
    ALLERGY = "allergy"
    CLINICAL_NOTE = "clinical_note"
    LAB_ORDER = "lab_order"
    LAB_SAMPLE = "lab_sample"
    LAB_RESULT = "lab_result"
    REPORT = "report"
    PRESCRIPTION = "prescription"
    APPOINTMENT = "appointment"
    ADMISSION = "admission"
    ADMISSION_TRANSFER = "admission_transfer"
    WORKFLOW_TASK = "workflow_task"


class TimelineParams(PageParams):
    types: list[TimelineEventType] | None = Field(
        default=None, description="Only these event types (repeat the parameter); default all"
    )
    occurred_from: AnyClinicalTimestamp | None = Field(default=None, description="Inclusive lower bound")
    occurred_to: AnyClinicalTimestamp | None = Field(default=None, description="Inclusive upper bound")
    order: Literal["asc", "desc"] = Field(default="desc", description="desc = newest first")

    @model_validator(mode="after")
    def _check_range(self) -> "TimelineParams":
        if self.occurred_from and self.occurred_to and self.occurred_to < self.occurred_from:
            raise ValueError("occurred_to cannot be before occurred_from")
        return self


class TimelineEvent(BaseModel):
    event_type: TimelineEventType
    occurred_at: datetime = Field(description="The clinical timestamp that places this event")
    record_id: uuid.UUID
    encounter_id: uuid.UUID | None
    title: str
    status: str | None
    data: dict[str, Any] = Field(description="The full underlying record")


class Timeline(BaseModel):
    patient_id: uuid.UUID
    items: list[TimelineEvent]
    total: int
    limit: int
    offset: int
    order: Literal["asc", "desc"]
