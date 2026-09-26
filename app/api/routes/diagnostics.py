"""Laboratory, Reports and Prescriptions endpoints (Stage 3).

Created/listed under their patient; each record is addressable by its own id; status
changes are explicit action endpoints. No DELETE anywhere.

    /api/patients/{patient_id}/lab-orders            POST, GET
    /api/lab-orders/{id}                             GET (with samples and results)
    /api/lab-orders/{id}/samples                     POST  (collect a sample)
    /api/lab-orders/{id}/start-processing            POST
    /api/lab-orders/{id}/results                     POST  (enter one or more results)
    /api/lab-orders/{id}/verify|release|cancel       POST
    /api/lab-samples/{id}                            GET
    /api/lab-results/{id}                            GET, PATCH (correction before verification)

    /api/patients/{patient_id}/reports               POST, GET
    /api/reports/{id}                                GET, PATCH (DRAFT only)
    /api/reports/{id}/verify|release|cancel          POST

    /api/patients/{patient_id}/prescriptions         POST, GET
    /api/prescriptions/{id}                          GET, PATCH (DRAFT notes)
    /api/prescriptions/{id}/items                    POST  (DRAFT only)
    /api/prescriptions/{id}/activate|hold|resume|complete|cancel   POST
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
from app.schemas.diagnostics import (
    CancelRequest,
    LabOrderCreate,
    LabOrderListParams,
    LabOrderRead,
    LabResultRead,
    LabResultsSubmit,
    LabResultUpdate,
    LabSampleCreate,
    LabSampleRead,
    LabVerify,
    PrescriptionCreate,
    PrescriptionItemCreate,
    PrescriptionListParams,
    PrescriptionRead,
    PrescriptionUpdate,
    ReportCreate,
    ReportListParams,
    ReportRead,
    ReportUpdate,
    ReportVerify,
)
from app.services.laboratory_service import LabOrderService
from app.services.prescription_service import PrescriptionService
from app.services.report_service import ReportService

router = APIRouter(prefix="/api")

_ERRORS = {
    404: {"description": "Patient or record not found"},
    409: {"description": "Invalid status transition, inactive patient, or conflicting record"},
    503: {"description": "Database unavailable"},
}
PATIENT = "/patients/{patient_id}"


def _service[S](cls: type[S]):
    def dependency(session: Session = Depends(get_db)) -> S:
        return cls(session)

    return Depends(dependency)


Labs = Annotated[LabOrderService, _service(LabOrderService)]
Reports = Annotated[ReportService, _service(ReportService)]
Prescriptions = Annotated[PrescriptionService, _service(PrescriptionService)]


def _created(response: Response, path: str, record_id: uuid.UUID) -> None:
    response.headers["Location"] = f"{router.prefix}/{path}/{record_id}"


def _page(schema, result: tuple[list, int], params) -> dict:
    items, total = result
    return {"items": [schema.model_validate(i) for i in items], "total": total,
            "limit": params.limit, "offset": params.offset}


# --- laboratory -----------------------------------------------------------------------

LAB = ["laboratory"]


@router.post(f"{PATIENT}/lab-orders", response_model=LabOrderRead, status_code=status.HTTP_201_CREATED,
             responses=_ERRORS, tags=LAB)
def create_lab_order(patient_id: uuid.UUID, data: LabOrderCreate, response: Response, service: Labs, principal: Annotated[Principal, requires(P.LAB_ORDER)]):
    data = bind_actor(data, principal, "ordered_by_staff_id", "ordered_by")
    order = service.create(patient_id, data)
    _created(response, "lab-orders", order.id)
    return order


@router.get(f"{PATIENT}/lab-orders", response_model=Page[LabOrderRead], responses=_ERRORS, tags=LAB, dependencies=[requires(P.LAB_VIEW)])
def list_lab_orders(patient_id: uuid.UUID, params: Annotated[LabOrderListParams, Query()], service: Labs):
    return _page(LabOrderRead, service.list_for_patient(patient_id, params), params)


@router.get("/lab-orders/{order_id}", response_model=LabOrderRead, responses=_ERRORS, tags=LAB, dependencies=[requires(P.LAB_VIEW)])
def get_lab_order(order_id: uuid.UUID, service: Labs):
    return service.get(order_id)


@router.post("/lab-orders/{order_id}/samples", response_model=LabSampleRead, status_code=status.HTTP_201_CREATED,
             responses=_ERRORS, tags=LAB)
def collect_lab_sample(order_id: uuid.UUID, data: LabSampleCreate, response: Response, service: Labs, principal: Annotated[Principal, requires(P.LAB_COLLECT)]):
    data = bind_actor(data, principal, "collected_by_staff_id", "collected_by")
    sample = service.collect_sample(order_id, data)
    _created(response, "lab-samples", sample.id)
    return sample


@router.post("/lab-orders/{order_id}/start-processing", response_model=LabOrderRead, responses=_ERRORS, tags=LAB, dependencies=[requires(P.LAB_PROCESS)])
def start_lab_processing(order_id: uuid.UUID, service: Labs):
    return service.start_processing(order_id)


@router.post("/lab-orders/{order_id}/results", response_model=LabOrderRead, responses=_ERRORS, tags=LAB)
def submit_lab_results(order_id: uuid.UUID, data: LabResultsSubmit, service: Labs, principal: Annotated[Principal, requires(P.LAB_PROCESS)]):
    data = bind_actor(data, principal, "entered_by_staff_id", "entered_by")
    return service.submit_results(order_id, data)


@router.post("/lab-orders/{order_id}/verify", response_model=LabOrderRead, responses=_ERRORS, tags=LAB)
def verify_lab_order(order_id: uuid.UUID, data: LabVerify, service: Labs, principal: Annotated[Principal, requires(P.LAB_VERIFY)]):
    data = bind_actor(data, principal, "verified_by_staff_id", "verified_by")
    return service.verify(order_id, data)


@router.post("/lab-orders/{order_id}/release", response_model=LabOrderRead, responses=_ERRORS, tags=LAB, dependencies=[requires(P.LAB_VERIFY)])
def release_lab_order(order_id: uuid.UUID, service: Labs):
    return service.release(order_id)


@router.post("/lab-orders/{order_id}/cancel", response_model=LabOrderRead, responses=_ERRORS, tags=LAB, dependencies=[requires(P.LAB_ORDER)])
def cancel_lab_order(order_id: uuid.UUID, data: CancelRequest, service: Labs):
    return service.cancel(order_id, data)


@router.get("/lab-samples/{sample_id}", response_model=LabSampleRead, responses=_ERRORS, tags=LAB, dependencies=[requires(P.LAB_VIEW)])
def get_lab_sample(sample_id: uuid.UUID, service: Labs):
    return service.get_sample(sample_id)


@router.get("/lab-results/{result_id}", response_model=LabResultRead, responses=_ERRORS, tags=LAB, dependencies=[requires(P.LAB_VIEW)])
def get_lab_result(result_id: uuid.UUID, service: Labs):
    return service.get_result(result_id)


@router.patch("/lab-results/{result_id}", response_model=LabResultRead, responses=_ERRORS, tags=LAB)
def correct_lab_result(result_id: uuid.UUID, data: LabResultUpdate, service: Labs, principal: Annotated[Principal, requires(P.LAB_PROCESS)]):
    data = bind_actor(data, principal, "entered_by_staff_id", "entered_by")
    return service.update_result(result_id, data)


# --- reports ----------------------------------------------------------------------------

REPORTS = ["reports"]


@router.post(f"{PATIENT}/reports", response_model=ReportRead, status_code=status.HTTP_201_CREATED,
             responses=_ERRORS, tags=REPORTS)
def create_report(patient_id: uuid.UUID, data: ReportCreate, response: Response, service: Reports, principal: Annotated[Principal, requires(P.REPORT_CREATE)]):
    data = bind_actor(data, principal, "author_staff_id", "author_name")
    report = service.create(patient_id, data)
    _created(response, "reports", report.id)
    return report


@router.get(f"{PATIENT}/reports", response_model=Page[ReportRead], responses=_ERRORS, tags=REPORTS, dependencies=[requires(P.REPORT_VIEW)])
def list_reports(patient_id: uuid.UUID, params: Annotated[ReportListParams, Query()], service: Reports):
    return _page(ReportRead, service.list_for_patient(patient_id, params), params)


@router.get("/reports/{report_id}", response_model=ReportRead, responses=_ERRORS, tags=REPORTS, dependencies=[requires(P.REPORT_VIEW)])
def get_report(report_id: uuid.UUID, service: Reports):
    return service.get(report_id)


@router.patch("/reports/{report_id}", response_model=ReportRead, responses=_ERRORS, tags=REPORTS, dependencies=[requires(P.REPORT_CREATE)])
def update_report(report_id: uuid.UUID, data: ReportUpdate, service: Reports):
    return service.update(report_id, data)


@router.post("/reports/{report_id}/verify", response_model=ReportRead, responses=_ERRORS, tags=REPORTS)
def verify_report(report_id: uuid.UUID, data: ReportVerify, service: Reports, principal: Annotated[Principal, requires(P.REPORT_VERIFY)]):
    data = bind_actor(data, principal, "verified_by_staff_id", "verified_by")
    return service.verify(report_id, data)


@router.post("/reports/{report_id}/release", response_model=ReportRead, responses=_ERRORS, tags=REPORTS, dependencies=[requires(P.REPORT_VERIFY)])
def release_report(report_id: uuid.UUID, service: Reports):
    return service.release(report_id)


@router.post("/reports/{report_id}/cancel", response_model=ReportRead, responses=_ERRORS, tags=REPORTS, dependencies=[requires(P.REPORT_CREATE)])
def cancel_report(report_id: uuid.UUID, data: CancelRequest, service: Reports):
    return service.cancel(report_id, data)


# --- prescriptions ------------------------------------------------------------------------

RX = ["prescriptions"]


@router.post(f"{PATIENT}/prescriptions", response_model=PrescriptionRead, status_code=status.HTTP_201_CREATED,
             responses=_ERRORS, tags=RX)
def create_prescription(patient_id: uuid.UUID, data: PrescriptionCreate, response: Response, service: Prescriptions, principal: Annotated[Principal, requires(P.PRESCRIPTION_CREATE)]):
    data = bind_actor(data, principal, "prescriber_staff_id", "prescriber_name")
    prescription = service.create(patient_id, data)
    _created(response, "prescriptions", prescription.id)
    return prescription


@router.get(f"{PATIENT}/prescriptions", response_model=Page[PrescriptionRead], responses=_ERRORS, tags=RX, dependencies=[requires(P.PRESCRIPTION_VIEW)])
def list_prescriptions(patient_id: uuid.UUID, params: Annotated[PrescriptionListParams, Query()],
                       service: Prescriptions):
    return _page(PrescriptionRead, service.list_for_patient(patient_id, params), params)


@router.get("/prescriptions/{prescription_id}", response_model=PrescriptionRead, responses=_ERRORS, tags=RX, dependencies=[requires(P.PRESCRIPTION_VIEW)])
def get_prescription(prescription_id: uuid.UUID, service: Prescriptions):
    return service.get(prescription_id)


@router.patch("/prescriptions/{prescription_id}", response_model=PrescriptionRead, responses=_ERRORS, tags=RX, dependencies=[requires(P.PRESCRIPTION_CREATE)])
def update_prescription(prescription_id: uuid.UUID, data: PrescriptionUpdate, service: Prescriptions):
    return service.update(prescription_id, data)


@router.post("/prescriptions/{prescription_id}/items", response_model=PrescriptionRead, responses=_ERRORS, tags=RX, dependencies=[requires(P.PRESCRIPTION_CREATE)])
def add_prescription_item(prescription_id: uuid.UUID, data: PrescriptionItemCreate, service: Prescriptions):
    return service.add_item(prescription_id, data)


@router.post("/prescriptions/{prescription_id}/activate", response_model=PrescriptionRead, responses=_ERRORS, tags=RX, dependencies=[requires(P.PRESCRIPTION_CREATE)])
def activate_prescription(prescription_id: uuid.UUID, service: Prescriptions):
    return service.activate(prescription_id)


@router.post("/prescriptions/{prescription_id}/hold", response_model=PrescriptionRead, responses=_ERRORS, tags=RX, dependencies=[requires(P.PRESCRIPTION_EDIT)])
def hold_prescription(prescription_id: uuid.UUID, service: Prescriptions):
    return service.hold(prescription_id)


@router.post("/prescriptions/{prescription_id}/resume", response_model=PrescriptionRead, responses=_ERRORS, tags=RX, dependencies=[requires(P.PRESCRIPTION_EDIT)])
def resume_prescription(prescription_id: uuid.UUID, service: Prescriptions):
    return service.resume(prescription_id)


@router.post("/prescriptions/{prescription_id}/complete", response_model=PrescriptionRead, responses=_ERRORS, tags=RX, dependencies=[requires(P.PRESCRIPTION_EDIT)])
def complete_prescription(prescription_id: uuid.UUID, service: Prescriptions):
    return service.complete(prescription_id)


@router.post("/prescriptions/{prescription_id}/cancel", response_model=PrescriptionRead, responses=_ERRORS, tags=RX, dependencies=[requires(P.PRESCRIPTION_EDIT)])
def cancel_prescription(prescription_id: uuid.UUID, data: CancelRequest, service: Prescriptions):
    return service.cancel(prescription_id, data)
