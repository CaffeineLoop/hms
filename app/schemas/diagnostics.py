"""API contracts for Stage 3: laboratory, reports and prescriptions.

Timestamps follow the Stage 2 policy (app/schemas/common.py): timezone-aware input only,
stored/returned in UTC, not before 1900, not in the future (5 min skew). Rules that need
the database (patient/encounter/order ownership, lifecycle state, ordering against
related records) live in the services.
"""

import math
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator

from app.models.laboratory import LabOrderStatus, LabPriority, ResultInterpretation, SpecimenType
from app.models.prescription import DurationUnit, Frequency, PrescriptionStatus, Route
from app.models.report import ReportStatus, ReportType
from app.schemas.common import (
    CodeSystem,
    ExternalCode,
    OptionalText500,
    OptionalText1000,
    PageParams,
    PastClinicalTimestamp,
    Text200,
    Text255,
    Text500,
    optional_text,
    require_one_person,
    text,
)

MAX_ITEMS_PER_PRESCRIPTION = 50
MAX_RESULTS_PER_SUBMISSION = 100
MAX_DURATION = {DurationUnit.DAYS: 3650, DurationUnit.WEEKS: 520, DurationUnit.MONTHS: 120}


def _lower(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


# Lower-cased BEFORE the pattern check (same convention as observation codes).
LocalCode = Annotated[str, BeforeValidator(_lower), StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
OptionalText2000 = optional_text(2000)
OptionalReportText = optional_text(100_000)
OptionalText100 = optional_text(100)
Unit = optional_text(32)
RequiredUnit = text(32)


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _require_complete_coding(system, code, system_field: str, code_field: str) -> None:
    if (system is None) != (code is None):
        raise ValueError(f"{system_field} and {code_field} must be given together")


def _require_finite(value: float | None, field: str) -> None:
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")


# --- laboratory -----------------------------------------------------------------------


class LabOrderCreate(_Input):
    encounter_id: uuid.UUID
    test_code: LocalCode = Field(description="HMS test code, e.g. full_blood_count, malaria_rdt")
    test_name: Text255
    code_system: CodeSystem = None
    system_code: ExternalCode = None
    priority: LabPriority = LabPriority.ROUTINE
    clinical_indication: OptionalText500 = None
    ordered_by_staff_id: uuid.UUID | None = Field(default=None, description="Staff member (Stage 4); preferred over the legacy free-text name")
    ordered_by: Text200 | None = Field(default=None, description="Legacy free-text orderer")
    ordered_at: PastClinicalTimestamp | None = Field(default=None, description="Defaults to now")

    @model_validator(mode="after")
    def _check(self) -> "LabOrderCreate":
        _require_complete_coding(self.code_system, self.system_code, "code_system", "system_code")
        require_one_person(self, "ordered_by", "ordered_by_staff_id", required=False)
        return self


class LabSampleCreate(_Input):
    specimen_type: SpecimenType
    collected_by_staff_id: uuid.UUID | None = Field(default=None, description="Staff member (Stage 4); preferred over the legacy free-text name")
    collected_by: Text200 | None = Field(default=None, description="Legacy free-text collector")
    collected_at: PastClinicalTimestamp | None = Field(default=None, description="Defaults to now")
    notes: OptionalText1000 = None

    @model_validator(mode="after")
    def _check(self) -> "LabSampleCreate":
        require_one_person(self, "collected_by", "collected_by_staff_id", required=False)
        return self


class LabResultFields(_Input):
    value_numeric: float | None = None
    value_text: OptionalText500 = None
    unit: Unit = None
    reference_low: float | None = None
    reference_high: float | None = None
    reference_text: OptionalText100 = None
    interpretation: ResultInterpretation | None = Field(
        default=None, description="Derived from the reference range when omitted for numeric results"
    )
    notes: OptionalText1000 = None


def check_result_values(values: dict) -> None:
    """Shared by create and (merged) update validation."""
    numeric, text_value = values.get("value_numeric"), values.get("value_text")
    if (numeric is None) == (text_value is None):
        raise ValueError("exactly one of value_numeric or value_text is required")
    for field in ("value_numeric", "reference_low", "reference_high"):
        _require_finite(values.get(field), field)
    if text_value is not None:
        if values.get("unit") is not None:
            raise ValueError("unit is only allowed with value_numeric")
        if values.get("reference_low") is not None or values.get("reference_high") is not None:
            raise ValueError("reference_low/reference_high are only allowed with value_numeric")
    low, high = values.get("reference_low"), values.get("reference_high")
    if low is not None and high is not None and low > high:
        raise ValueError("reference_low cannot be greater than reference_high")


def derive_interpretation(value: float | None, low: float | None, high: float | None) -> ResultInterpretation | None:
    if value is None or (low is None and high is None):
        return None
    if low is not None and value < low:
        return ResultInterpretation.LOW
    if high is not None and value > high:
        return ResultInterpretation.HIGH
    return ResultInterpretation.NORMAL


class LabResultCreate(LabResultFields):
    analyte_code: LocalCode = Field(description="HMS analyte code, e.g. hemoglobin")
    analyte_name: Text255
    code_system: CodeSystem = None
    system_code: ExternalCode = None
    resulted_at: PastClinicalTimestamp | None = Field(default=None, description="Defaults to now")

    @model_validator(mode="after")
    def _check(self) -> "LabResultCreate":
        _require_complete_coding(self.code_system, self.system_code, "code_system", "system_code")
        check_result_values(self.model_dump())
        if self.interpretation is None:
            self.interpretation = derive_interpretation(self.value_numeric, self.reference_low, self.reference_high)
        return self


class LabResultsSubmit(_Input):
    entered_by_staff_id: uuid.UUID | None = Field(default=None, description="Staff member (Stage 4); preferred over the legacy free-text name")
    entered_by: Text200 | None = Field(default=None, description="Legacy free-text technician")
    results: list[LabResultCreate] = Field(min_length=1, max_length=MAX_RESULTS_PER_SUBMISSION)

    @model_validator(mode="after")
    def _unique_analytes(self) -> "LabResultsSubmit":
        require_one_person(self, "entered_by", "entered_by_staff_id", required=False)
        codes = [r.analyte_code for r in self.results]
        if len(codes) != len(set(codes)):
            raise ValueError("each analyte_code may appear only once per submission")
        return self


class LabResultUpdate(LabResultFields):
    """Correction before verification. Omitted fields keep their value."""

    entered_by_staff_id: uuid.UUID | None = Field(default=None, description="Staff member (Stage 4); preferred over the legacy free-text name")
    entered_by: Text200 | None = Field(default=None, description="Legacy free-text technician")

    @model_validator(mode="after")
    def _check(self) -> "LabResultUpdate":
        require_one_person(self, "entered_by", "entered_by_staff_id", required=False)
        if self.model_fields_set <= {"entered_by", "entered_by_staff_id"}:
            raise ValueError("at least one result field must be provided")
        return self


class LabVerify(_Input):
    verified_by_staff_id: uuid.UUID | None = Field(default=None, description="Staff member (Stage 4); preferred over the legacy free-text name")
    verified_by: Text200 | None = Field(default=None, description="Legacy free-text verifier")

    @model_validator(mode="after")
    def _check(self) -> "LabVerify":
        require_one_person(self, "verified_by", "verified_by_staff_id", required=False)
        return self


class CancelRequest(_Input):
    reason: Text500


class LabSampleRead(_Output):
    id: uuid.UUID
    patient_id: uuid.UUID
    lab_order_id: uuid.UUID
    accession_number: str
    specimen_type: SpecimenType
    collected_at: datetime
    collected_by: str
    collected_by_staff_id: uuid.UUID | None
    notes: str | None
    created_at: datetime


class LabResultRead(_Output):
    id: uuid.UUID
    patient_id: uuid.UUID
    lab_order_id: uuid.UUID
    analyte_code: str
    analyte_name: str
    code_system: str | None
    system_code: str | None
    value_numeric: float | None
    value_text: str | None
    unit: str | None
    reference_low: float | None
    reference_high: float | None
    reference_text: str | None
    interpretation: ResultInterpretation | None
    resulted_at: datetime
    entered_by: str
    entered_by_staff_id: uuid.UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class LabOrderSummaryRead(_Output):
    """A lab order without its samples/results (used where results must not be exposed)."""

    id: uuid.UUID
    patient_id: uuid.UUID
    encounter_id: uuid.UUID
    order_number: str
    test_code: str
    test_name: str
    code_system: str | None
    system_code: str | None
    priority: LabPriority
    status: LabOrderStatus
    clinical_indication: str | None
    ordered_by: str
    ordered_by_staff_id: uuid.UUID | None
    ordered_at: datetime
    processing_started_at: datetime | None
    results_entered_at: datetime | None
    verified_by: str | None
    verified_by_staff_id: uuid.UUID | None
    verified_at: datetime | None
    released_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime


class LabOrderRead(LabOrderSummaryRead):
    samples: list[LabSampleRead]
    results: list[LabResultRead]


class LabOrderListParams(PageParams):
    status: LabOrderStatus | None = None
    encounter_id: uuid.UUID | None = None
    test_code: LocalCode | None = None


# --- reports ----------------------------------------------------------------------------


class ReportCreate(_Input):
    report_type: ReportType
    title: Text255
    code_system: CodeSystem = None
    code: ExternalCode = None
    encounter_id: uuid.UUID | None = None
    lab_order_id: uuid.UUID | None = Field(default=None, description="Only for LABORATORY reports")
    effective_at: PastClinicalTimestamp | None = Field(
        default=None, description="Clinically relevant time the report covers; defaults to now"
    )
    requested_by_staff_id: uuid.UUID | None = Field(default=None, description="Staff member (Stage 4); preferred over the legacy free-text name")
    requested_by: optional_text(200) = Field(default=None, description="Legacy free-text requester")
    requested_at: PastClinicalTimestamp | None = None
    author_staff_id: uuid.UUID | None = Field(default=None, description="Staff member (Stage 4); preferred over the legacy free-text name")
    author_name: Text200 | None = Field(default=None, description="Legacy free-text author")
    content: OptionalReportText = None
    conclusion: OptionalText2000 = None

    @model_validator(mode="after")
    def _check(self) -> "ReportCreate":
        _require_complete_coding(self.code_system, self.code, "code_system", "code")
        if self.lab_order_id is not None and self.report_type != ReportType.LABORATORY:
            raise ValueError("lab_order_id is only allowed for LABORATORY reports")
        require_one_person(self, "author_name", "author_staff_id", required=False)
        require_one_person(self, "requested_by", "requested_by_staff_id", required=False)
        return self


class ReportUpdate(_Input):
    """Edit a DRAFT report. Omitted fields keep their value."""

    title: Text255 | None = None
    content: OptionalReportText = None
    conclusion: OptionalText2000 = None

    @model_validator(mode="after")
    def _check(self) -> "ReportUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        return self


class ReportVerify(_Input):
    verified_by_staff_id: uuid.UUID | None = Field(default=None, description="Staff member (Stage 4); preferred over the legacy free-text name")
    verified_by: Text200 | None = Field(default=None, description="Legacy free-text verifier")

    @model_validator(mode="after")
    def _check(self) -> "ReportVerify":
        require_one_person(self, "verified_by", "verified_by_staff_id", required=False)
        return self


class ReportRead(_Output):
    id: uuid.UUID
    patient_id: uuid.UUID
    encounter_id: uuid.UUID | None
    lab_order_id: uuid.UUID | None
    report_type: ReportType
    title: str
    code_system: str | None
    code: str | None
    status: ReportStatus
    effective_at: datetime
    requested_by: str | None
    requested_by_staff_id: uuid.UUID | None
    requested_at: datetime | None
    author_name: str
    author_staff_id: uuid.UUID | None
    content: str | None
    conclusion: str | None
    verified_by: str | None
    verified_by_staff_id: uuid.UUID | None
    verified_at: datetime | None
    released_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime


class ReportListParams(PageParams):
    status: ReportStatus | None = None
    report_type: ReportType | None = None
    encounter_id: uuid.UUID | None = None


# --- prescriptions ----------------------------------------------------------------------


class PrescriptionItemCreate(_Input):
    medicine_name: Text255 = Field(description="Medicine incl. strength/form, e.g. 'Amoxicillin 500 mg capsule'")
    code_system: CodeSystem = None
    code: ExternalCode = Field(default=None, description="e.g. RxNorm code")
    dose_value: float = Field(gt=0, le=100_000)
    dose_unit: RequiredUnit = Field(description="e.g. mg, mL, tablet, puff")
    route: Route
    frequency: Frequency
    duration_value: int | None = Field(default=None, gt=0)
    duration_unit: DurationUnit | None = None
    quantity: float | None = Field(default=None, gt=0, le=100_000)
    quantity_unit: Unit = None
    instructions: OptionalText1000 = None

    @model_validator(mode="after")
    def _check(self) -> "PrescriptionItemCreate":
        _require_complete_coding(self.code_system, self.code, "code_system", "code")
        _require_finite(self.dose_value, "dose_value")
        _require_finite(self.quantity, "quantity")
        if (self.duration_value is None) != (self.duration_unit is None):
            raise ValueError("duration_value and duration_unit must be given together")
        if self.duration_unit is not None and self.duration_value > MAX_DURATION[self.duration_unit]:
            raise ValueError(f"duration cannot exceed {MAX_DURATION[self.duration_unit]} {self.duration_unit.value}")
        if self.quantity_unit is not None and self.quantity is None:
            raise ValueError("quantity_unit requires quantity")
        if self.frequency == Frequency.PRN and self.instructions is None:
            raise ValueError("PRN (as needed) items require instructions (indication / maximum dose)")
        return self


class PrescriptionCreate(_Input):
    encounter_id: uuid.UUID
    prescriber_staff_id: uuid.UUID | None = Field(default=None, description="Staff member (Stage 4); preferred over the legacy free-text name")
    prescriber_name: Text200 | None = Field(default=None, description="Legacy free-text prescriber")
    prescribed_at: PastClinicalTimestamp | None = Field(default=None, description="Defaults to now")
    notes: OptionalText2000 = None
    items: list[PrescriptionItemCreate] = Field(min_length=1, max_length=MAX_ITEMS_PER_PRESCRIPTION)

    @model_validator(mode="after")
    def _check(self) -> "PrescriptionCreate":
        require_one_person(self, "prescriber_name", "prescriber_staff_id", required=False)
        return self


class PrescriptionUpdate(_Input):
    """Edit a DRAFT prescription's notes."""

    notes: OptionalText2000

    @model_validator(mode="before")
    @classmethod
    def _require_notes(cls, data):
        if isinstance(data, dict) and "notes" not in data:
            raise ValueError("notes must be provided")
        return data


class PrescriptionItemRead(_Output):
    id: uuid.UUID
    prescription_id: uuid.UUID
    line_number: int
    medicine_name: str
    code_system: str | None
    code: str | None
    dose_value: float
    dose_unit: str
    route: Route
    frequency: Frequency
    duration_value: int | None
    duration_unit: DurationUnit | None
    quantity: float | None
    quantity_unit: str | None
    instructions: str | None
    created_at: datetime


class PrescriptionRead(_Output):
    id: uuid.UUID
    patient_id: uuid.UUID
    encounter_id: uuid.UUID
    prescription_number: str
    prescriber_name: str
    prescriber_staff_id: uuid.UUID | None
    status: PrescriptionStatus
    prescribed_at: datetime
    activated_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    notes: str | None
    items: list[PrescriptionItemRead]
    created_at: datetime
    updated_at: datetime


class PrescriptionListParams(PageParams):
    status: PrescriptionStatus | None = None
    encounter_id: uuid.UUID | None = None
