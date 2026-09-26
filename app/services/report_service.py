"""Clinical reports. See app/models/report.py for the lifecycle.

Rules:
- created as DRAFT for an ACTIVE patient; an optional encounter must be the patient's
  and have taken place; an optional lab order must be the patient's and not CANCELLED;
- only DRAFT reports can be edited; verification requires content;
- a LABORATORY report linked to a lab order can be RELEASED only after that order's
  results are RELEASED (unverified results are never published through a report).
"""

import uuid

from sqlalchemy.orm import Session

from app.core.clock import now_not_before as not_before
from app.core.clock import utc_now
from app.core.errors import BusinessValidationError, ConflictError, NotFoundError
from app.models.laboratory import LabOrderStatus
from app.models.report import REPORT_TRANSITIONS, Report, ReportStatus
from app.repositories.clinical_repository import LabOrderRepository, ReportRepository
from app.schemas.diagnostics import CancelRequest, ReportCreate, ReportListParams, ReportUpdate, ReportVerify
from app.services.clinical_common import (
    ClinicalContext,
    check_not_before_birth,
    check_not_before_encounter,
    ensure_transition,
)
from app.services.staff_directory import StaffDirectory


class ReportService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._reports = ReportRepository(session)
        self._orders = LabOrderRepository(session)
        self._context = ClinicalContext(session)
        self._directory = StaffDirectory(session)

    def get(self, report_id: uuid.UUID) -> Report:
        return self._get(report_id)

    def list_for_patient(self, patient_id: uuid.UUID, params: ReportListParams) -> tuple[list[Report], int]:
        self._context.patient(patient_id)
        return self._reports.list_for_patient(
            patient_id,
            filters={"status": params.status, "report_type": params.report_type, "encounter_id": params.encounter_id},
            limit=params.limit,
            offset=params.offset,
        )

    def create(self, patient_id: uuid.UUID, data: ReportCreate) -> Report:
        patient = self._context.patient_for_recording(patient_id)
        encounter = self._context.encounter_for_recording(patient, data.encounter_id)
        if data.lab_order_id is not None:
            order = self._orders.get(data.lab_order_id)
            if order is None or order.patient_id != patient.id:
                raise BusinessValidationError(
                    f"lab order {data.lab_order_id} does not exist for patient {patient.patient_number}",
                    field="lab_order_id",
                )
            if order.status == LabOrderStatus.CANCELLED:
                raise ConflictError(f"Lab order {order.order_number} is CANCELLED; it cannot be reported.")
        values = data.model_dump()
        values["effective_at"] = data.effective_at or utc_now()
        values["author_staff_id"], values["author_name"] = self._directory.person(
            data.author_staff_id, data.author_name, "author_staff_id"
        )
        values["requested_by_staff_id"], values["requested_by"] = self._directory.person(
            data.requested_by_staff_id, data.requested_by, "requested_by_staff_id", required=False
        )
        for field in ("effective_at", "requested_at"):
            check_not_before_birth(patient, values[field], field)
        check_not_before_encounter(encounter, values["effective_at"], "effective_at")
        report = Report(patient_id=patient.id, status=ReportStatus.DRAFT.value, **values)
        self._reports.add(report)
        return self._save(report)

    def update(self, report_id: uuid.UUID, data: ReportUpdate) -> Report:
        report = self._get(report_id, for_update=True)
        if report.status != ReportStatus.DRAFT:
            raise ConflictError(f"Report {report.id} is {report.status}; only DRAFT reports can be edited.")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(report, field, value)
        return self._save(report)

    def verify(self, report_id: uuid.UUID, data: ReportVerify) -> Report:
        report = self._get(report_id, for_update=True)
        self._transition(report, ReportStatus.VERIFIED)
        if not (report.content and report.content.strip()):
            raise BusinessValidationError("a report needs content before it can be verified", field="content")
        report.status = ReportStatus.VERIFIED.value
        report.verified_by_staff_id, report.verified_by = self._directory.person(
            data.verified_by_staff_id, data.verified_by, "verified_by_staff_id"
        )
        report.verified_at = utc_now()
        return self._save(report)

    def release(self, report_id: uuid.UUID) -> Report:
        report = self._get(report_id, for_update=True)
        self._transition(report, ReportStatus.RELEASED)
        if report.lab_order_id is not None:
            order = self._orders.get(report.lab_order_id)
            if order.status != LabOrderStatus.RELEASED:
                raise ConflictError(
                    f"Lab order {order.order_number} is {order.status}; its results must be RELEASED "
                    "before this report can be released."
                )
        report.status = ReportStatus.RELEASED.value
        report.released_at = not_before(report.verified_at)
        return self._save(report)

    def cancel(self, report_id: uuid.UUID, data: CancelRequest) -> Report:
        report = self._get(report_id, for_update=True)
        self._transition(report, ReportStatus.CANCELLED)
        report.status = ReportStatus.CANCELLED.value
        report.cancelled_at = utc_now()
        report.cancellation_reason = data.reason
        return self._save(report)

    def _transition(self, report: Report, target: ReportStatus) -> None:
        ensure_transition(f"Report {report.id}", report.status, target, REPORT_TRANSITIONS)

    def _save(self, report: Report) -> Report:
        self._session.commit()
        self._session.refresh(report)
        return report

    def _get(self, report_id: uuid.UUID, *, for_update: bool = False) -> Report:
        report = self._reports.get(report_id, for_update=for_update)
        if report is None:
            raise NotFoundError(f"Report {report_id} not found.")
        return report
