"""Departments and staff endpoints (Stage 4). No authentication/authorization yet (Stage 5).

    /api/departments                         POST, GET
    /api/departments/{id}                    GET, PATCH
    /api/departments/{id}/deactivate|reactivate   POST
    /api/staff                               POST, GET
    /api/staff/{id}                          GET, PATCH
    /api/staff/{id}/deactivate|reactivate    POST
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.auth import requires
from app.core.permissions import P
from app.db.session import get_db
from app.models.staff import RecordStatus
from app.schemas.common import Page
from app.schemas.staff import (
    DepartmentCreate,
    DepartmentListParams,
    DepartmentRead,
    DepartmentUpdate,
    StaffCreate,
    StaffListParams,
    StaffRead,
    StaffUpdate,
)
from app.services.staff_service import DepartmentService, StaffService

router = APIRouter(prefix="/api")

_ERRORS = {
    404: {"description": "Not found"},
    409: {"description": "Duplicate, or already in the requested state"},
    503: {"description": "Database unavailable"},
}


def _departments(session: Session = Depends(get_db)) -> DepartmentService:
    return DepartmentService(session)


def _staff(session: Session = Depends(get_db)) -> StaffService:
    return StaffService(session)


Departments = Annotated[DepartmentService, Depends(_departments)]
StaffDep = Annotated[StaffService, Depends(_staff)]


def _page(schema, result, params) -> dict:
    items, total = result
    return {"items": [schema.model_validate(i) for i in items], "total": total,
            "limit": params.limit, "offset": params.offset}


# --- departments -----------------------------------------------------------------------

DEPT = ["departments"]


@router.post("/departments", response_model=DepartmentRead, status_code=status.HTTP_201_CREATED,
             responses=_ERRORS, tags=DEPT, dependencies=[requires(P.STAFF_MANAGE)])
def create_department(data: DepartmentCreate, response: Response, service: Departments):
    department = service.create(data)
    response.headers["Location"] = f"/api/departments/{department.id}"
    return department


@router.get("/departments", response_model=Page[DepartmentRead], responses=_ERRORS, tags=DEPT, dependencies=[requires(P.STAFF_VIEW)])
def list_departments(params: Annotated[DepartmentListParams, Query()], service: Departments):
    return _page(DepartmentRead, service.search(params), params)


@router.get("/departments/{department_id}", response_model=DepartmentRead, responses=_ERRORS, tags=DEPT, dependencies=[requires(P.STAFF_VIEW)])
def get_department(department_id: uuid.UUID, service: Departments):
    return service.get(department_id)


@router.patch("/departments/{department_id}", response_model=DepartmentRead, responses=_ERRORS, tags=DEPT, dependencies=[requires(P.STAFF_MANAGE)])
def update_department(department_id: uuid.UUID, data: DepartmentUpdate, service: Departments):
    return service.update(department_id, data)


@router.post("/departments/{department_id}/deactivate", response_model=DepartmentRead, responses=_ERRORS, tags=DEPT, dependencies=[requires(P.STAFF_MANAGE)])
def deactivate_department(department_id: uuid.UUID, service: Departments):
    return service.set_status(department_id, RecordStatus.INACTIVE)


@router.post("/departments/{department_id}/reactivate", response_model=DepartmentRead, responses=_ERRORS, tags=DEPT, dependencies=[requires(P.STAFF_MANAGE)])
def reactivate_department(department_id: uuid.UUID, service: Departments):
    return service.set_status(department_id, RecordStatus.ACTIVE)


# --- staff ---------------------------------------------------------------------------------

STAFF = ["staff"]


@router.post("/staff", response_model=StaffRead, status_code=status.HTTP_201_CREATED, responses=_ERRORS, tags=STAFF, dependencies=[requires(P.STAFF_MANAGE)])
def create_staff(data: StaffCreate, response: Response, service: StaffDep):
    staff = service.create(data)
    response.headers["Location"] = f"/api/staff/{staff.id}"
    return staff


@router.get("/staff", response_model=Page[StaffRead], responses=_ERRORS, tags=STAFF, dependencies=[requires(P.STAFF_VIEW)])
def list_staff(params: Annotated[StaffListParams, Query()], service: StaffDep):
    return _page(StaffRead, service.search(params), params)


@router.get("/staff/{staff_id}", response_model=StaffRead, responses=_ERRORS, tags=STAFF, dependencies=[requires(P.STAFF_VIEW)])
def get_staff(staff_id: uuid.UUID, service: StaffDep):
    return service.get(staff_id)


@router.patch("/staff/{staff_id}", response_model=StaffRead, responses=_ERRORS, tags=STAFF, dependencies=[requires(P.STAFF_MANAGE)])
def update_staff(staff_id: uuid.UUID, data: StaffUpdate, service: StaffDep):
    return service.update(staff_id, data)


@router.post("/staff/{staff_id}/deactivate", response_model=StaffRead, responses=_ERRORS, tags=STAFF, dependencies=[requires(P.STAFF_MANAGE)])
def deactivate_staff(staff_id: uuid.UUID, service: StaffDep):
    return service.deactivate(staff_id)


@router.post("/staff/{staff_id}/reactivate", response_model=StaffRead, responses=_ERRORS, tags=STAFF, dependencies=[requires(P.STAFF_MANAGE)])
def reactivate_staff(staff_id: uuid.UUID, service: StaffDep):
    return service.reactivate(staff_id)
