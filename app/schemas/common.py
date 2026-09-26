"""Reusable schema building blocks for clinical records (Stage 2 onwards)."""

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator, Field, StringConstraints

from app.core.clock import latest_allowed_instant

MIN_CLINICAL_INSTANT = datetime(1900, 1, 1, tzinfo=UTC)
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


def blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def text(max_length: int) -> Any:
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)]


def optional_text(max_length: int) -> Any:
    return Annotated[text(max_length) | None, BeforeValidator(blank_to_none)]


Text200 = text(200)
Text255 = text(255)
Text500 = text(500)
Text100000 = text(100_000)
OptionalText500 = optional_text(500)
OptionalText1000 = optional_text(1000)
OptionalText10000 = optional_text(10_000)


def _to_utc_in_range(value: datetime) -> datetime:
    value = value.astimezone(UTC)
    if value < MIN_CLINICAL_INSTANT:
        raise ValueError("timestamp cannot be before 1900-01-01T00:00:00Z")
    return value


def _not_in_future(value: datetime) -> datetime:
    if value > latest_allowed_instant():
        raise ValueError("timestamp cannot be in the future")
    return value


# Timezone-aware input is mandatory (naive timestamps are rejected); stored in UTC.
AnyClinicalTimestamp = Annotated[AwareDatetime, AfterValidator(_to_utc_in_range)]
PastClinicalTimestamp = Annotated[AnyClinicalTimestamp, AfterValidator(_not_in_future)]

CodeSystem = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100, pattern=r"^\S+$")]
    | None,
    BeforeValidator(blank_to_none),
]
ExternalCode = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^\S+$")]
    | None,
    BeforeValidator(blank_to_none),
]


class PageParams(BaseModel):
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0)


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


def require_one_person(model: BaseModel, name_field: str, staff_field: str, *, required: bool = True) -> None:
    """Stage 4 person references: a record names a person EITHER by staff id (preferred) OR by
    the legacy free-text name kept for backward compatibility - never both."""
    name, staff_id = getattr(model, name_field), getattr(model, staff_field)
    if name is not None and staff_id is not None:
        raise ValueError(f"give either {staff_field} or {name_field}, not both")
    if required and name is None and staff_id is None:
        raise ValueError(f"{staff_field} is required (or the legacy free-text {name_field})")
