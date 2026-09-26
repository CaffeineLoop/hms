"""Departments and staff administration (Stage 4). No authentication/authorization here.

Rules:
- department names are unique (case-insensitive); employee codes and staff emails are unique;
- staff must belong to an existing, ACTIVE department;
- nothing is deleted: departments and staff are deactivated/reactivated explicitly (409 when
  already in the requested state). Inactive staff/departments keep their history but cannot
  be given new work (see StaffDirectory).
"""

import uuid

from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.errors import ConflictError, NotFoundError
from app.models.staff import Department, RecordStatus, Staff
from app.models.auth import RevocationReason
from app.repositories.auth_repository import SessionRepository, UserRepository
from app.repositories.staff_repository import DepartmentRepository, StaffRepository
from app.schemas.staff import DepartmentCreate, DepartmentListParams, DepartmentUpdate, StaffCreate, StaffListParams, StaffUpdate
from app.services.staff_directory import StaffDirectory


class DepartmentService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._departments = DepartmentRepository(session)

    def get(self, department_id: uuid.UUID) -> Department:
        return self._get(department_id)

    def search(self, params: DepartmentListParams) -> tuple[list[Department], int]:
        return self._departments.search(status=params.status, q=params.q, limit=params.limit, offset=params.offset)

    def create(self, data: DepartmentCreate) -> Department:
        self._ensure_unique_name(data.name)
        department = Department(name=data.name, description=data.description, status=RecordStatus.ACTIVE.value)
        self._departments.add(department)
        return self._save(department)

    def update(self, department_id: uuid.UUID, data: DepartmentUpdate) -> Department:
        department = self._get(department_id, for_update=True)
        changes = data.model_dump(exclude_unset=True)
        if "name" in changes:
            self._ensure_unique_name(changes["name"], exclude_id=department.id)
        for field, value in changes.items():
            setattr(department, field, value)
        return self._save(department)

    def set_status(self, department_id: uuid.UUID, status: RecordStatus) -> Department:
        department = self._get(department_id, for_update=True)
        if department.status == status:
            raise ConflictError(f"Department {department.name} is already {status.value}.")
        department.status = status.value
        return self._save(department)

    def _ensure_unique_name(self, name: str, exclude_id: uuid.UUID | None = None) -> None:
        if self._departments.by_name(name, exclude_id=exclude_id) is not None:
            raise ConflictError(f"A department named '{name}' already exists.")

    def _save(self, department: Department) -> Department:
        self._session.commit()
        self._session.refresh(department)
        return department

    def _get(self, department_id: uuid.UUID, *, for_update: bool = False) -> Department:
        department = self._departments.get(department_id, for_update=for_update)
        if department is None:
            raise NotFoundError(f"Department {department_id} not found.")
        return department


class StaffService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._staff = StaffRepository(session)
        self._users = UserRepository(session)
        self._directory = StaffDirectory(session)

    def get(self, staff_id: uuid.UUID) -> Staff:
        return self._get(staff_id)

    def search(self, params: StaffListParams) -> tuple[list[Staff], int]:
        filters = {"department_id": params.department_id, "designation": params.designation, "status": params.status}
        return self._staff.search(filters=filters, q=params.q, limit=params.limit, offset=params.offset)

    def create(self, data: StaffCreate) -> Staff:
        self._directory.active_department(data.department_id, "department_id")
        if self._staff.by_employee_code(data.employee_code) is not None:
            raise ConflictError(f"Employee code {data.employee_code} is already in use.")
        if data.email and self._staff.by_email(data.email) is not None:
            raise ConflictError(f"A staff member with email {data.email} already exists.")
        staff = Staff(**data.model_dump(), status=RecordStatus.ACTIVE.value)
        self._staff.add(staff)
        return self._save(staff)

    def update(self, staff_id: uuid.UUID, data: StaffUpdate) -> Staff:
        staff = self._get(staff_id, for_update=True)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("department_id") not in (None, staff.department_id):
            self._directory.active_department(changes["department_id"], "department_id")
        if changes.get("email") and self._staff.by_email(changes["email"], exclude_id=staff.id) is not None:
            raise ConflictError(f"A staff member with email {changes['email']} already exists.")
        for field, value in changes.items():
            setattr(staff, field, value)
        return self._save(staff)

    def deactivate(self, staff_id: uuid.UUID) -> Staff:
        staff = self._get(staff_id, for_update=True)
        if staff.status == RecordStatus.INACTIVE:
            raise ConflictError(f"Staff member {staff.employee_code} is already INACTIVE.")
        # Stage 5: deactivating staff disables their login; never lock out the last superuser.
        user = self._users.by_staff_id(staff.id)
        if user is not None and self._users.effective_grants(user.id)[0] and self._users.count_active_superusers() <= 1:
            raise ConflictError("This staff member is the last active superuser; create another one first.")
        staff.status = RecordStatus.INACTIVE.value
        staff.deactivated_at = utc_now()
        if user is not None:  # Stage 6: revoke their sessions explicitly (auth also re-checks status)
            SessionRepository(self._session).revoke_for_user(
                user.id, staff.deactivated_at, RevocationReason.STAFF_DEACTIVATED.value
            )
        return self._save(staff)

    def reactivate(self, staff_id: uuid.UUID) -> Staff:
        staff = self._get(staff_id, for_update=True)
        if staff.status == RecordStatus.ACTIVE:
            raise ConflictError(f"Staff member {staff.employee_code} is already ACTIVE.")
        self._directory.active_department(staff.department_id, "department_id")
        staff.status = RecordStatus.ACTIVE.value
        staff.deactivated_at = None
        return self._save(staff)

    def _save(self, staff: Staff) -> Staff:
        self._session.commit()
        self._session.refresh(staff)
        return staff

    def _get(self, staff_id: uuid.UUID, *, for_update: bool = False) -> Staff:
        staff = self._staff.get(staff_id, for_update=for_update)
        if staff is None:
            raise NotFoundError(f"Staff member {staff_id} not found.")
        return staff
