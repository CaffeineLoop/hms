"""Resolves staff and department references used by other services (Stage 4).

- A referenced staff member / department must exist (422, the reference is part of the
  request body) and be ACTIVE (409, it exists but cannot take on new work).
- `person()` implements the Stage 4 reference rule for records that historically stored a
  free-text name: given a staff id it returns (staff_id, current full name) so the name
  column keeps a snapshot; given only the legacy name it returns (None, name).
"""

import uuid

from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ConflictError
from app.models.staff import Department, RecordStatus, Staff
from app.repositories.staff_repository import DepartmentRepository, StaffRepository


class StaffDirectory:
    def __init__(self, session: Session) -> None:
        self._staff = StaffRepository(session)
        self._departments = DepartmentRepository(session)

    def active_staff(self, staff_id: uuid.UUID, field: str) -> Staff:
        staff = self._staff.get(staff_id)
        if staff is None:
            raise BusinessValidationError(f"{field} {staff_id} does not refer to a staff member", field=field)
        if staff.status != RecordStatus.ACTIVE:
            raise ConflictError(f"Staff member {staff.employee_code} is inactive.")
        return staff

    def optional_staff(self, staff_id: uuid.UUID | None, field: str) -> Staff | None:
        return None if staff_id is None else self.active_staff(staff_id, field)

    def active_department(self, department_id: uuid.UUID, field: str) -> Department:
        department = self._departments.get(department_id)
        if department is None:
            raise BusinessValidationError(
                f"{field} {department_id} does not refer to a department", field=field
            )
        if department.status != RecordStatus.ACTIVE:
            raise ConflictError(f"Department {department.name} is inactive.")
        return department

    def person(self, staff_id: uuid.UUID | None, name: str | None, field: str, *,
               required: bool = True) -> tuple[uuid.UUID | None, str | None]:
        if staff_id is None:
            if name is None and required:
                raise BusinessValidationError(f"{field} is required", field=field)
            return None, name
        staff = self.active_staff(staff_id, field)
        return staff.id, staff.full_name
