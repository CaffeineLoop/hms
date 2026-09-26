"""Patient Management endpoints (Stage 1).

POST   /api/patients                      register a patient            201 / 409 / 422
GET    /api/patients                      list, search, filter, paginate 200 / 422
GET    /api/patients/{id}                 retrieve by internal UUID      200 / 404 / 422
PATCH  /api/patients/{id}                 partial update                 200 / 404 / 409 / 422
POST   /api/patients/{id}/deactivate      controlled deactivation        200 / 404 / 409 / 422
POST   /api/patients/{id}/reactivate      undo a deactivation            200 / 404 / 409

There is deliberately no DELETE: patient records are never physically removed.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.auth import requires
from app.core.permissions import P
from app.db.session import get_db
from app.schemas.patient import (
    PatientCreate,
    PatientDeactivate,
    PatientList,
    PatientListParams,
    PatientRead,
    PatientUpdate,
)
from app.services.patient_service import PatientService

router = APIRouter(prefix="/api/patients", tags=["patients"])

_ERRORS = {
    404: {"description": "Patient not found"},
    409: {"description": "Conflicts with existing data or the patient's current status"},
    503: {"description": "Database unavailable"},
}


def get_patient_service(session: Session = Depends(get_db)) -> PatientService:
    return PatientService(session)


Service = Annotated[PatientService, Depends(get_patient_service)]


@router.post(
    "",
    response_model=PatientRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: _ERRORS[409], 503: _ERRORS[503]}, dependencies=[requires(P.PATIENT_CREATE)])
def create_patient(data: PatientCreate, response: Response, service: Service) -> PatientRead:
    patient = service.create(data)
    response.headers["Location"] = f"{router.prefix}/{patient.id}"
    return PatientRead.model_validate(patient)


@router.get("", response_model=PatientList, responses={503: _ERRORS[503]}, dependencies=[requires(P.PATIENT_VIEW)])
def list_patients(params: Annotated[PatientListParams, Query()], service: Service) -> PatientList:
    patients, total = service.search(params)
    return PatientList(
        items=[PatientRead.model_validate(p) for p in patients],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.get("/{patient_id}", response_model=PatientRead, responses={404: _ERRORS[404], 503: _ERRORS[503]}, dependencies=[requires(P.PATIENT_VIEW)])
def get_patient(patient_id: uuid.UUID, service: Service) -> PatientRead:
    return PatientRead.model_validate(service.get(patient_id))


@router.patch("/{patient_id}", response_model=PatientRead, responses=_ERRORS, dependencies=[requires(P.PATIENT_EDIT)])
def update_patient(patient_id: uuid.UUID, data: PatientUpdate, service: Service) -> PatientRead:
    return PatientRead.model_validate(service.update(patient_id, data))


@router.post("/{patient_id}/deactivate", response_model=PatientRead, responses=_ERRORS, dependencies=[requires(P.PATIENT_EDIT)])
def deactivate_patient(patient_id: uuid.UUID, data: PatientDeactivate, service: Service) -> PatientRead:
    return PatientRead.model_validate(service.deactivate(patient_id, data.reason))


@router.post("/{patient_id}/reactivate", response_model=PatientRead, responses=_ERRORS, dependencies=[requires(P.PATIENT_EDIT)])
def reactivate_patient(patient_id: uuid.UUID, service: Service) -> PatientRead:
    return PatientRead.model_validate(service.reactivate(patient_id))
