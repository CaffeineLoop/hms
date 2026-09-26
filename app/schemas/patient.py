"""API contracts for Patient Management.

Input normalization happens here so every layer below sees clean values:
- surrounding whitespace is stripped; blank optional strings become null
- phone numbers are stored in one deterministic form: separators removed, the
  international prefix '00' rewritten as '+', then either '+<country code><number>'
  (E.164 shape) or a national number of 7-15 digits
- email addresses are lower-cased
"""

import re
import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.clock import facility_today
from app.models.patient import PatientStatus, Sex

MIN_DATE_OF_BIRTH = date(1900, 1, 1)
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20

_PHONE_SEPARATORS = re.compile(r"[\s\-().]")
_PHONE = re.compile(r"^(\+[1-9][0-9]{6,14}|[0-9]{7,15})$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def normalize_phone(value: str) -> str:
    compact = _PHONE_SEPARATORS.sub("", value)
    if compact.startswith("00"):
        compact = "+" + compact[2:]
    if not _PHONE.fullmatch(compact):
        raise ValueError(
            "phone must be an international number (+ or 00, country code, 7-15 digits in total) "
            "or a 7-15 digit national number (spaces, dashes, dots and parentheses are allowed)"
        )
    return compact


def _normalize_email(value: str) -> str:
    value = value.lower()
    if not _EMAIL.fullmatch(value):
        raise ValueError("email must be a valid email address")
    return value


def _check_date_of_birth(value: date) -> date:
    if value > facility_today():
        raise ValueError("date_of_birth cannot be in the future")
    if value < MIN_DATE_OF_BIRTH:
        raise ValueError(f"date_of_birth cannot be before {MIN_DATE_OF_BIRTH.isoformat()}")
    return value


def _text(max_length: int) -> Any:
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)]


def _optional_text(max_length: int) -> Any:
    return Annotated[_text(max_length) | None, BeforeValidator(_blank_to_none)]


Name = _text(100)
OptionalName = _optional_text(100)
OptionalText20 = _optional_text(20)
OptionalText50 = _optional_text(50)
OptionalText100 = _optional_text(100)
OptionalText200 = _optional_text(200)
Reason = _text(500)
DateOfBirth = Annotated[date, AfterValidator(_check_date_of_birth)]
Phone = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=30), AfterValidator(normalize_phone)] | None,
    BeforeValidator(_blank_to_none),
]
Email = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=254), AfterValidator(_normalize_email)]
    | None,
    BeforeValidator(_blank_to_none),
]


class _PatientFields(BaseModel):
    """Fields shared by create and update. All optional here; PatientCreate tightens them."""

    model_config = ConfigDict(extra="forbid")

    middle_name: OptionalName = None
    phone: Phone = None
    email: Email = None

    address_line1: OptionalText200 = None
    address_line2: OptionalText200 = None
    city: OptionalText100 = None
    state_province: OptionalText100 = None
    postal_code: OptionalText20 = None
    country: OptionalText100 = None

    emergency_contact_name: OptionalText200 = None
    emergency_contact_relationship: OptionalText50 = None
    emergency_contact_phone: Phone = None


class PatientCreate(_PatientFields):
    first_name: Name
    last_name: Name
    date_of_birth: DateOfBirth
    sex: Sex


# Identity fields that may be changed but never cleared.
REQUIRED_ON_UPDATE = ("first_name", "last_name", "date_of_birth", "sex")


class PatientUpdate(_PatientFields):
    """Partial update (PATCH). Omitted fields are unchanged; optional fields may be set to null.

    `status`, `patient_number` and timestamps are not updatable here (extra fields are
    rejected); status changes go through the deactivate/reactivate endpoints.
    """

    first_name: Name | None = None
    last_name: Name | None = None
    date_of_birth: DateOfBirth | None = None
    sex: Sex | None = None

    @model_validator(mode="after")
    def _check_fields(self) -> "PatientUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        for field in REQUIRED_ON_UPDATE:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class PatientDeactivate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class PatientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_number: str
    first_name: str
    middle_name: str | None
    last_name: str
    date_of_birth: date
    sex: Sex
    phone: str | None
    email: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    state_province: str | None
    postal_code: str | None
    country: str | None
    emergency_contact_name: str | None
    emergency_contact_relationship: str | None
    emergency_contact_phone: str | None
    status: PatientStatus
    deactivated_at: datetime | None
    deactivation_reason: str | None
    created_at: datetime
    updated_at: datetime


class PatientListParams(BaseModel):
    """Query parameters for GET /api/patients."""

    q: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=100)] = Field(
        default=None,
        description="Search by Patient ID, first/middle/last or full name, phone, or email.",
    )
    status: PatientStatus | None = None
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0)


class PatientList(BaseModel):
    items: list[PatientRead]
    total: int
    limit: int
    offset: int
