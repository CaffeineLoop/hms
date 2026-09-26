"""Data access for appointments, admissions (and transfers) and workflow tasks."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import case, select

from app.models.workflow import OPEN_ADMISSION_STATUSES, Admission, AdmissionTransfer, Appointment, WorkflowTask
from app.repositories.staff_repository import BaseRepository


class AppointmentRepository(BaseRepository):
    model = Appointment

    def search(
        self,
        *,
        filters: dict[str, Any],
        scheduled_from: datetime | None = None,
        scheduled_to: datetime | None = None,
        newest_first: bool = False,
        limit: int,
        offset: int,
    ) -> tuple[list[Appointment], int]:
        statement = self._filtered(filters)
        if scheduled_from is not None:
            statement = statement.where(Appointment.scheduled_start >= scheduled_from)
        if scheduled_to is not None:
            statement = statement.where(Appointment.scheduled_start <= scheduled_to)
        start = Appointment.scheduled_start.desc() if newest_first else Appointment.scheduled_start.asc()
        return self._page(statement, (start, Appointment.created_at, Appointment.id), limit, offset)


class AdmissionRepository(BaseRepository):
    model = Admission

    def open_for_patient(self, patient_id: uuid.UUID) -> Admission | None:
        statement = select(Admission).where(
            Admission.patient_id == patient_id, Admission.status.in_(OPEN_ADMISSION_STATUSES)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def search(self, *, filters: dict[str, Any], limit: int, offset: int) -> tuple[list[Admission], int]:
        order = (Admission.requested_at.desc(), Admission.created_at.desc(), Admission.id)
        return self._page(self._filtered(filters), order, limit, offset)

    def add_transfer(self, transfer: AdmissionTransfer) -> AdmissionTransfer:
        return self.add(transfer)


_PRIORITY_ORDER = case(
    {"URGENT": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}, value=WorkflowTask.priority, else_=4
)


class TaskRepository(BaseRepository):
    model = WorkflowTask

    def search(self, *, filters: dict[str, Any], limit: int, offset: int) -> tuple[list[WorkflowTask], int]:
        # Work queue order: most urgent first, then earliest due (undated last), then oldest.
        order = (
            _PRIORITY_ORDER,
            WorkflowTask.due_at.asc().nulls_last(),
            WorkflowTask.created_at,
            WorkflowTask.id,
        )
        return self._page(self._filtered(filters), order, limit, offset)
