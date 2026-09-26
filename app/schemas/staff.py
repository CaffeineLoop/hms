"""API contracts for departments and staff (Stage 4). No accounts or permissions here."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator

from app.models.staff import Designation, RecordStatus
from app.schemas.common import PageParams, optional_text, text
from app.schemas.patient import Email, Phone


def _upper(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


EmployeeCode = Annotated[
    str, BeforeValidator(_upper), StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9-]{1,19}$")
]
Name = text(100)
Search = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=100)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _require_some_field(model: BaseModel, not_null: tuple[str, ...] = ()) -> None:
    if not model.model_fields_set:
        raise ValueError("at least one field must be provided")
    for field in not_null:
        if field in model.model_fields_set and getattr(model, field) is None:
            raise ValueError(f"{field} cannot be null")


# --- departments ----------------------------------------------------------------------


class DepartmentCreate(_Input):
    name: Name
    description: optional_text(500) = None


class DepartmentUpdate(_Input):
    name: Name | None = None
    description: optional_text(500) = None

    @model_validator(mode="after")
    def _check(self) -> "DepartmentUpdate":
        _require_some_field(self, ("name",))
        return self


class DepartmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    status: RecordStatus
    created_at: datetime
    updated_at: datetime


class DepartmentListParams(PageParams):
    status: RecordStatus | None = None
    q: Search = Field(default=None, description="Search by name")


# --- staff ----------------------------------------------------------------------------


class StaffCreate(_Input):
    employee_code: EmployeeCode = Field(description="HR-assigned code, e.g. EMP-0042 (stored upper-case)")
    first_name: Name
    last_name: Name
    designation: Designation
    department_id: uuid.UUID
    phone: Phone = None
    email: Email = None


class StaffUpdate(_Input):
    """employee_code is immutable; status changes use deactivate/reactivate."""

    first_name: Name | None = None
    last_name: Name | None = None
    designation: Designation | None = None
    department_id: uuid.UUID | None = None
    phone: Phone = None
    email: Email = None

    @model_validator(mode="after")
    def _check(self) -> "StaffUpdate":
        _require_some_field(self, ("first_name", "last_name", "designation", "department_id"))
        return self


class StaffRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_code: str
    first_name: str
    last_name: str
    full_name: str
    designation: Designation
    department_id: uuid.UUID
    phone: str | None
    email: str | None
    status: RecordStatus
    deactivated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StaffListParams(PageParams):
    department_id: uuid.UUID | None = None
    designation: Designation | None = None
    status: RecordStatus | None = None
    q: Search = Field(default=None, description="Search by employee code or name")
