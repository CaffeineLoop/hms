"""API contracts for Stage 2 clinical records.

Timestamp rules (see app/schemas/common.py):
- all timestamps must include a UTC offset (naive values are rejected) and are returned in UTC;
- clinical timestamps cannot be before 1900 and, except for a PLANNED encounter's start,
  cannot be in the future (5 minutes of clock skew tolerated).
Rules that need the database (patient exists/active, encounter belongs to the patient,
record not before the patient's birth, status transitions) live in the services.
"""

import math
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator

from app.core.clock import latest_allowed_instant
from app.models.allergy import AllergyCategory, AllergySeverity, AllergyStatus
from app.models.clinical_note import NoteType
from app.models.condition import ConditionStatus
from app.models.encounter import EncounterStatus, EncounterType
from app.schemas.common import (
    AnyClinicalTimestamp,
    CodeSystem,
    ExternalCode,
    OptionalText500,
    OptionalText1000,
    OptionalText10000,
    PageParams,
    PastClinicalTimestamp,
    Text200,
    require_one_person,
    Text255,
    Text500,
    Text100000,
    optional_text,
)
from app.services.observation_catalog import validate_observation

def _lower(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


# Lower-cased BEFORE the pattern check (StringConstraints would check the pattern first).
ObservationCode = Annotated[
    str, BeforeValidator(_lower), StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")
]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _require_complete_coding(system: str | None, code: str | None, system_field: str, code_field: str) -> None:
    if (system is None) != (code is None):
        raise ValueError(f"{system_field} and {code_field} must be given together")


def _require_some_field(model: BaseModel) -> None:
    if not model.model_fields_set:
        raise ValueError("at least one field must be provided")


# --- encounters ---------------------------------------------------------------


class EncounterCreate(_Input):
    """Open an encounter now (IN_PROGRESS, the default), book one (PLANNED), or document
    a past one (FINISHED, with start_at and end_at)."""

    encounter_type: EncounterType
    reason: Text500 = Field(description="Reason for visit / chief complaint")
    status: Literal[EncounterStatus.PLANNED, EncounterStatus.IN_PROGRESS, EncounterStatus.FINISHED] = (
        EncounterStatus.IN_PROGRESS
    )
    start_at: AnyClinicalTimestamp | None = Field(
        default=None, description="Required for PLANNED and FINISHED; defaults to now for IN_PROGRESS"
    )
    end_at: PastClinicalTimestamp | None = None
    summary: OptionalText10000 = None
    attending_staff_id: uuid.UUID | None = Field(default=None, description="Responsible clinician (Stage 4)")

    @model_validator(mode="after")
    def _check_timestamps(self) -> "EncounterCreate":
        if self.status != EncounterStatus.IN_PROGRESS and self.start_at is None:
            raise ValueError(f"start_at is required for a {self.status.value} encounter")
        if self.status == EncounterStatus.FINISHED:
            if self.end_at is None:
                raise ValueError("end_at is required for a FINISHED encounter")
        elif self.end_at is not None:
            raise ValueError("end_at can only be given for a FINISHED encounter")
        started = self.status != EncounterStatus.PLANNED
        if started and self.start_at is not None and self.start_at > latest_allowed_instant():
            raise ValueError("start_at cannot be in the future unless the encounter is PLANNED")
        if self.start_at and self.end_at and self.end_at < self.start_at:
            raise ValueError("end_at cannot be before start_at")
        return self


class EncounterStart(_Input):
    start_at: PastClinicalTimestamp | None = Field(default=None, description="Defaults to now")


class EncounterFinish(_Input):
    end_at: PastClinicalTimestamp | None = Field(default=None, description="Defaults to now")
    summary: OptionalText10000 = None


class EncounterCancel(_Input):
    reason: Text500


class EncounterRead(_Output):
    id: uuid.UUID
    patient_id: uuid.UUID
    encounter_type: EncounterType
    status: EncounterStatus
    reason: str
    start_at: datetime
    end_at: datetime | None
    summary: str | None
    cancellation_reason: str | None
    attending_staff_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class EncounterListParams(PageParams):
    status: EncounterStatus | None = None
    encounter_type: EncounterType | None = None


# --- observations -------------------------------------------------------------


class ObservationCreate(_Input):
    code: ObservationCode = Field(description="HMS observation code, e.g. heart_rate, body_temperature")
    display: optional_text(255) = Field(default=None, description="Required for codes outside the catalog")
    code_system: CodeSystem = None
    system_code: ExternalCode = None
    value_numeric: float | None = None
    value_text: OptionalText500 = None
    unit: optional_text(32) = None
    effective_at: PastClinicalTimestamp
    encounter_id: uuid.UUID | None = None
    notes: OptionalText1000 = None

    @model_validator(mode="after")
    def _check_value(self) -> "ObservationCreate":
        if (self.value_numeric is None) == (self.value_text is None):
            raise ValueError("exactly one of value_numeric or value_text is required")
        if self.value_numeric is not None and not math.isfinite(self.value_numeric):
            raise ValueError("value_numeric must be a finite number")
        if self.value_text is not None and self.unit is not None:
            raise ValueError("unit is only allowed with value_numeric")
        _require_complete_coding(self.code_system, self.system_code, "code_system", "system_code")
        resolved = validate_observation(
            code=self.code, value=self.value_numeric, unit=self.unit, display=self.display
        )
        self.display = resolved.display
        if resolved.code_system and self.code_system is None:
            self.code_system, self.system_code = resolved.code_system, resolved.system_code
        return self


class ObservationRead(_Output):
    id: uuid.UUID
    patient_id: uuid.UUID
    encounter_id: uuid.UUID | None
    code: str
    display: str
    code_system: str | None
    system_code: str | None
    value_numeric: float | None
    value_text: str | None
    unit: str | None
    effective_at: datetime
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ObservationListParams(PageParams):
    code: ObservationCode | None = None
    encounter_id: uuid.UUID | None = None


# --- conditions ---------------------------------------------------------------


class ConditionCreate(_Input):
    name: Text255
    code_system: CodeSystem = None
    code: ExternalCode = None
    status: ConditionStatus = ConditionStatus.ACTIVE
    onset_at: PastClinicalTimestamp | None = None
    resolved_at: PastClinicalTimestamp | None = None
    recorded_at: PastClinicalTimestamp | None = Field(default=None, description="Defaults to now")
    encounter_id: uuid.UUID | None = None
    notes: OptionalText10000 = None

    @model_validator(mode="after")
    def _check(self) -> "ConditionCreate":
        _require_complete_coding(self.code_system, self.code, "code_system", "code")
        if self.resolved_at and self.onset_at and self.resolved_at < self.onset_at:
            raise ValueError("resolved_at cannot be before onset_at")
        if self.resolved_at and self.status not in (ConditionStatus.RESOLVED, ConditionStatus.HISTORICAL):
            raise ValueError("resolved_at is only allowed for RESOLVED or HISTORICAL conditions")
        return self


class ConditionUpdate(_Input):
    """Status changes follow CONDITION_TRANSITIONS; other clinical facts are not rewritten."""

    status: ConditionStatus | None = None
    resolved_at: PastClinicalTimestamp | None = None
    notes: OptionalText10000 = None

    @model_validator(mode="after")
    def _check(self) -> "ConditionUpdate":
        _require_some_field(self)
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status cannot be null")
        return self


class ConditionRead(_Output):
    id: uuid.UUID
    patient_id: uuid.UUID
    encounter_id: uuid.UUID | None
    name: str
    code_system: str | None
    code: str | None
    status: ConditionStatus
    onset_at: datetime | None
    resolved_at: datetime | None
    recorded_at: datetime
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ConditionListParams(PageParams):
    status: ConditionStatus | None = None


# --- allergies ----------------------------------------------------------------


class AllergyCreate(_Input):
    substance: Text255
    code_system: CodeSystem = None
    code: ExternalCode = None
    category: AllergyCategory | None = None
    reaction: OptionalText500 = None
    severity: AllergySeverity | None = None
    status: AllergyStatus = AllergyStatus.ACTIVE
    onset_at: PastClinicalTimestamp | None = None
    recorded_at: PastClinicalTimestamp | None = Field(default=None, description="Defaults to now")
    encounter_id: uuid.UUID | None = None
    notes: OptionalText10000 = None

    @model_validator(mode="after")
    def _check(self) -> "AllergyCreate":
        _require_complete_coding(self.code_system, self.code, "code_system", "code")
        return self


class AllergyUpdate(_Input):
    status: AllergyStatus | None = None
    reaction: OptionalText500 = None
    severity: AllergySeverity | None = None
    notes: OptionalText10000 = None

    @model_validator(mode="after")
    def _check(self) -> "AllergyUpdate":
        _require_some_field(self)
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status cannot be null")
        return self


class AllergyRead(_Output):
    id: uuid.UUID
    patient_id: uuid.UUID
    encounter_id: uuid.UUID | None
    substance: str
    code_system: str | None
    code: str | None
    category: AllergyCategory | None
    reaction: str | None
    severity: AllergySeverity | None
    status: AllergyStatus
    onset_at: datetime | None
    recorded_at: datetime
    notes: str | None
    created_at: datetime
    updated_at: datetime


class AllergyListParams(PageParams):
    status: AllergyStatus | None = None


# --- clinical notes -----------------------------------------------------------


class ClinicalNoteCreate(_Input):
    encounter_id: uuid.UUID
    note_type: NoteType
    author_staff_id: uuid.UUID | None = Field(default=None, description="Staff member (Stage 4); preferred over the legacy free-text name")
    author_name: Text200 | None = Field(default=None, description="Legacy free-text author (use author_staff_id)")
    content: Text100000
    authored_at: PastClinicalTimestamp | None = Field(default=None, description="Defaults to now")

    @model_validator(mode="after")
    def _check_author(self) -> "ClinicalNoteCreate":
        require_one_person(self, "author_name", "author_staff_id", required=False)
        return self


class ClinicalNoteRead(_Output):
    id: uuid.UUID
    patient_id: uuid.UUID
    encounter_id: uuid.UUID
    note_type: NoteType
    author_name: str
    author_staff_id: uuid.UUID | None
    content: str
    authored_at: datetime
    created_at: datetime
    updated_at: datetime


class ClinicalNoteListParams(PageParams):
    encounter_id: uuid.UUID | None = None
    note_type: NoteType | None = None
