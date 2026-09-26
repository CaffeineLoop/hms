"""Appointments, admissions and workflow task endpoints (Stage 4). No authorization yet.

    /api/patients/{patient_id}/appointments          POST, GET
    /api/appointments                                GET  (schedule: staff/department/date filters)
    /api/appointments/{id}                           GET
    /api/appointments/{id}/confirm|check-in|start-consultation|complete|no-show|cancel   POST

    /api/patients/{patient_id}/admissions            POST, GET
    /api/admissions                                  GET  (e.g. ward census)
    /api/admissions/{id}                             GET (with transfer history)
    /api/admissions/{id}/approve|admit|transfer|discharge|cancel   POST

    /api/workflow-tasks                              POST, GET (work queue filters)
    /api/workflow-tasks/{id}                         GET, PATCH
    /api/workflow-tasks/{id}/assign|start|complete|cancel          POST
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.auth import requires
from app.api.authorship import bind_actor
from app.core.permissions import P
from app.core.principal import Principal
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.diagnostics import CancelRequest
from app.schemas.workflow import (
    AdmissionAdmit,
    AdmissionApprove,
    AdmissionCreate,
    AdmissionDischarge,
    AdmissionRead,
    AdmissionSearchParams,
    AdmissionTransferCreate,
    AppointmentComplete,
    AppointmentCreate,
    AppointmentRead,
    AppointmentSearchParams,
    AppointmentStartConsultation,
    PatientAdmissionListParams,
    PatientAppointmentListParams,
    TaskAssign,
    TaskComplete,
    TaskCreate,
    TaskRead,
    TaskSearchParams,
    TaskUpdate,
)
from app.services.admission_service import AdmissionService
from app.services.appointment_service import AppointmentService
from app.services.task_service import TaskService

router = APIRouter(prefix="/api")

_ERRORS = {
    404: {"description": "Patient or record not found"},
    409: {"description": "Invalid status transition, inactive patient/staff/department, or conflict"},
    503: {"description": "Database unavailable"},
}
PATIENT = "/patients/{patient_id}"


def _service[S](cls: type[S]):
    def dependency(session: Session = Depends(get_db)) -> S:
        return cls(session)

    return Depends(dependency)


Appointments = Annotated[AppointmentService, _service(AppointmentService)]
Admissions = Annotated[AdmissionService, _service(AdmissionService)]
Tasks = Annotated[TaskService, _service(TaskService)]
# Workflow tasks honour permission scope: OWN restricts the caller to tasks assigned to them.
TaskViewer = Annotated[Principal, requires(P.WORKFLOW_VIEW)]
TaskManager = Annotated[Principal, requires(P.WORKFLOW_MANAGE)]


def _page(schema, result, params) -> dict:
    items, total = result
    return {"items": [schema.model_validate(i) for i in items], "total": total,
            "limit": params.limit, "offset": params.offset}


# --- appointments --------------------------------------------------------------------------

APPT = ["appointments"]


@router.post(f"{PATIENT}/appointments", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED,
             responses=_ERRORS, tags=APPT, dependencies=[requires(P.APPOINTMENT_MANAGE)])
def book_appointment(patient_id: uuid.UUID, data: AppointmentCreate, response: Response, service: Appointments):
    appointment = service.create(patient_id, data)
    response.headers["Location"] = f"/api/appointments/{appointment.id}"
    return appointment


@router.get(f"{PATIENT}/appointments", response_model=Page[AppointmentRead], responses=_ERRORS, tags=APPT, dependencies=[requires(P.APPOINTMENT_VIEW)])
def list_patient_appointments(patient_id: uuid.UUID, params: Annotated[PatientAppointmentListParams, Query()],
                              service: Appointments):
    return _page(AppointmentRead, service.list_for_patient(patient_id, params), params)


@router.get("/appointments", response_model=Page[AppointmentRead], responses=_ERRORS, tags=APPT, dependencies=[requires(P.APPOINTMENT_VIEW)])
def search_appointments(params: Annotated[AppointmentSearchParams, Query()], service: Appointments):
    return _page(AppointmentRead, service.search(params), params)


@router.get("/appointments/{appointment_id}", response_model=AppointmentRead, responses=_ERRORS, tags=APPT, dependencies=[requires(P.APPOINTMENT_VIEW)])
def get_appointment(appointment_id: uuid.UUID, service: Appointments):
    return service.get(appointment_id)


@router.post("/appointments/{appointment_id}/confirm", response_model=AppointmentRead, responses=_ERRORS, tags=APPT, dependencies=[requires(P.APPOINTMENT_MANAGE)])
def confirm_appointment(appointment_id: uuid.UUID, service: Appointments):
    return service.confirm(appointment_id)


@router.post("/appointments/{appointment_id}/check-in", response_model=AppointmentRead, responses=_ERRORS, tags=APPT, dependencies=[requires(P.APPOINTMENT_MANAGE)])
def check_in_appointment(appointment_id: uuid.UUID, service: Appointments):
    return service.check_in(appointment_id)


@router.post("/appointments/{appointment_id}/start-consultation", response_model=AppointmentRead,
             responses=_ERRORS, tags=APPT, dependencies=[requires(P.APPOINTMENT_MANAGE)])
def start_consultation(appointment_id: uuid.UUID, service: Appointments,
                       data: AppointmentStartConsultation | None = None):
    return service.start_consultation(appointment_id, data or AppointmentStartConsultation())


@router.post("/appointments/{appointment_id}/complete", response_model=AppointmentRead, responses=_ERRORS, tags=APPT, dependencies=[requires(P.APPOINTMENT_MANAGE)])
def complete_appointment(appointment_id: uuid.UUID, service: Appointments, data: AppointmentComplete | None = None):
    return service.complete(appointment_id, data or AppointmentComplete())


@router.post("/appointments/{appointment_id}/no-show", response_model=AppointmentRead, responses=_ERRORS, tags=APPT, dependencies=[requires(P.APPOINTMENT_MANAGE)])
def mark_no_show(appointment_id: uuid.UUID, service: Appointments):
    return service.no_show(appointment_id)


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentRead, responses=_ERRORS, tags=APPT, dependencies=[requires(P.APPOINTMENT_MANAGE)])
def cancel_appointment(appointment_id: uuid.UUID, data: CancelRequest, service: Appointments):
    return service.cancel(appointment_id, data)


# --- admissions ------------------------------------------------------------------------------

ADM = ["admissions"]


@router.post(f"{PATIENT}/admissions", response_model=AdmissionRead, status_code=status.HTTP_201_CREATED,
             responses=_ERRORS, tags=ADM)
def request_admission(patient_id: uuid.UUID, data: AdmissionCreate, response: Response, service: Admissions, principal: Annotated[Principal, requires(P.ADMISSION_MANAGE)]):
    data = bind_actor(data, principal, "requested_by_staff_id")
    admission = service.create(patient_id, data)
    response.headers["Location"] = f"/api/admissions/{admission.id}"
    return admission


@router.get(f"{PATIENT}/admissions", response_model=Page[AdmissionRead], responses=_ERRORS, tags=ADM, dependencies=[requires(P.ADMISSION_VIEW)])
def list_patient_admissions(patient_id: uuid.UUID, params: Annotated[PatientAdmissionListParams, Query()],
                            service: Admissions):
    return _page(AdmissionRead, service.list_for_patient(patient_id, params), params)


@router.get("/admissions", response_model=Page[AdmissionRead], responses=_ERRORS, tags=ADM, dependencies=[requires(P.ADMISSION_VIEW)])
def search_admissions(params: Annotated[AdmissionSearchParams, Query()], service: Admissions):
    return _page(AdmissionRead, service.search(params), params)


@router.get("/admissions/{admission_id}", response_model=AdmissionRead, responses=_ERRORS, tags=ADM, dependencies=[requires(P.ADMISSION_VIEW)])
def get_admission(admission_id: uuid.UUID, service: Admissions):
    return service.get(admission_id)


@router.post("/admissions/{admission_id}/approve", response_model=AdmissionRead, responses=_ERRORS, tags=ADM)
def approve_admission(admission_id: uuid.UUID, data: AdmissionApprove, service: Admissions, principal: Annotated[Principal, requires(P.ADMISSION_MANAGE)]):
    data = bind_actor(data, principal, "approved_by_staff_id")
    return service.approve(admission_id, data)


@router.post("/admissions/{admission_id}/admit", response_model=AdmissionRead, responses=_ERRORS, tags=ADM, dependencies=[requires(P.ADMISSION_MANAGE)])
def admit_patient(admission_id: uuid.UUID, service: Admissions, data: AdmissionAdmit | None = None):
    return service.admit(admission_id, data or AdmissionAdmit())


@router.post("/admissions/{admission_id}/transfer", response_model=AdmissionRead, responses=_ERRORS, tags=ADM)
def transfer_patient(admission_id: uuid.UUID, data: AdmissionTransferCreate, service: Admissions, principal: Annotated[Principal, requires(P.ADMISSION_MANAGE)]):
    data = bind_actor(data, principal, "transferred_by_staff_id")
    return service.transfer(admission_id, data)


@router.post("/admissions/{admission_id}/discharge", response_model=AdmissionRead, responses=_ERRORS, tags=ADM, dependencies=[requires(P.ADMISSION_MANAGE)])
def discharge_patient(admission_id: uuid.UUID, data: AdmissionDischarge, service: Admissions):
    return service.discharge(admission_id, data)


@router.post("/admissions/{admission_id}/cancel", response_model=AdmissionRead, responses=_ERRORS, tags=ADM, dependencies=[requires(P.ADMISSION_MANAGE)])
def cancel_admission(admission_id: uuid.UUID, data: CancelRequest, service: Admissions):
    return service.cancel(admission_id, data)


# --- workflow tasks -------------------------------------------------------------------------

TASK = ["workflow tasks"]


@router.post("/workflow-tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED, responses=_ERRORS,
             tags=TASK)
def create_task(data: TaskCreate, response: Response, service: Tasks, principal: TaskManager):
    data = bind_actor(data, principal, "created_by_staff_id")
    task = service.create(data, own_staff_id=principal.own_staff_filter(P.WORKFLOW_MANAGE))
    response.headers["Location"] = f"/api/workflow-tasks/{task.id}"
    return task


@router.get("/workflow-tasks", response_model=Page[TaskRead], responses=_ERRORS, tags=TASK)
def search_tasks(params: Annotated[TaskSearchParams, Query()], service: Tasks, principal: TaskViewer):
    return _page(TaskRead, service.search(params, own_staff_id=principal.own_staff_filter(P.WORKFLOW_VIEW)), params)


@router.get("/workflow-tasks/{task_id}", response_model=TaskRead, responses=_ERRORS, tags=TASK)
def get_task(task_id: uuid.UUID, service: Tasks, principal: TaskViewer):
    return service.get(task_id, own_staff_id=principal.own_staff_filter(P.WORKFLOW_VIEW))


@router.patch("/workflow-tasks/{task_id}", response_model=TaskRead, responses=_ERRORS, tags=TASK)
def update_task(task_id: uuid.UUID, data: TaskUpdate, service: Tasks, principal: TaskManager):
    return service.update(task_id, data, own_staff_id=principal.own_staff_filter(P.WORKFLOW_MANAGE))


@router.post("/workflow-tasks/{task_id}/assign", response_model=TaskRead, responses=_ERRORS, tags=TASK)
def assign_task(task_id: uuid.UUID, data: TaskAssign, service: Tasks, principal: TaskManager):
    return service.assign(task_id, data, own_staff_id=principal.own_staff_filter(P.WORKFLOW_MANAGE))


@router.post("/workflow-tasks/{task_id}/start", response_model=TaskRead, responses=_ERRORS, tags=TASK)
def start_task(task_id: uuid.UUID, service: Tasks, principal: TaskManager):
    return service.start(task_id, own_staff_id=principal.own_staff_filter(P.WORKFLOW_MANAGE))


@router.post("/workflow-tasks/{task_id}/complete", response_model=TaskRead, responses=_ERRORS, tags=TASK)
def complete_task(task_id: uuid.UUID, service: Tasks, principal: TaskManager, data: TaskComplete | None = None):
    return service.complete(task_id, data or TaskComplete(), own_staff_id=principal.own_staff_filter(P.WORKFLOW_MANAGE))


@router.post("/workflow-tasks/{task_id}/cancel", response_model=TaskRead, responses=_ERRORS, tags=TASK)
def cancel_task(task_id: uuid.UUID, data: CancelRequest, service: Tasks, principal: TaskManager):
    return service.cancel(task_id, data, own_staff_id=principal.own_staff_filter(P.WORKFLOW_MANAGE))
