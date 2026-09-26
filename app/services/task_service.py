"""Workflow tasks: simple work allocation. See app/models/workflow.py for the lifecycle.

Rules:
- referenced patient/department/staff must exist (422); departments and staff must be ACTIVE (409);
- a task created with an assignee starts ASSIGNED; `assign` on an ASSIGNED / IN_PROGRESS task
  re-assigns it to a different staff member without changing its status;
- details (title, description, priority, due date) can be edited until the task is finished;
- other status changes go through TASK_TRANSITIONS (409 otherwise).
Scope (Stage 5): callers whose workflow permission is OWN-scoped pass `own_staff_id`; they only
see and progress tasks assigned to them (others are reported as not found) and cannot create,
edit or (re)assign tasks, which needs ALL scope (403).
"""

import uuid

from sqlalchemy.orm import Session

from app.core.clock import now_not_before, utc_now
from app.core.errors import BusinessValidationError, ConflictError, NotFoundError, PermissionDeniedError
from app.models.workflow import TASK_TRANSITIONS, TaskStatus, WorkflowTask
from app.repositories.patient_repository import PatientRepository
from app.repositories.workflow_repository import TaskRepository
from app.schemas.diagnostics import CancelRequest
from app.schemas.workflow import TaskAssign, TaskComplete, TaskCreate, TaskSearchParams, TaskUpdate
from app.services.clinical_common import ensure_transition
from app.services.staff_directory import StaffDirectory

_REASSIGNABLE = {TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS}
_FINISHED = {TaskStatus.COMPLETED, TaskStatus.CANCELLED}


class TaskService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._tasks = TaskRepository(session)
        self._patients = PatientRepository(session)
        self._directory = StaffDirectory(session)

    def get(self, task_id: uuid.UUID, *, own_staff_id: uuid.UUID | None = None) -> WorkflowTask:
        return self._get(task_id, own_staff_id=own_staff_id)

    def search(self, params: TaskSearchParams, *, own_staff_id: uuid.UUID | None = None):
        filters = params.model_dump(exclude={"limit", "offset"})
        if own_staff_id is not None:
            if filters["assigned_staff_id"] not in (None, own_staff_id):
                return [], 0
            filters["assigned_staff_id"] = own_staff_id
        return self._tasks.search(filters=filters, limit=params.limit, offset=params.offset)

    def create(self, data: TaskCreate, *, own_staff_id: uuid.UUID | None = None) -> WorkflowTask:
        _require_all_scope(own_staff_id, "create tasks")
        if data.patient_id is not None and self._patients.get(data.patient_id) is None:
            raise BusinessValidationError(f"patient_id {data.patient_id} does not refer to a patient", field="patient_id")
        if data.department_id is not None:
            self._directory.active_department(data.department_id, "department_id")
        self._directory.optional_staff(data.created_by_staff_id, "created_by_staff_id")
        assignee = self._directory.optional_staff(data.assigned_staff_id, "assigned_staff_id")
        task = WorkflowTask(
            **data.model_dump(),
            status=(TaskStatus.ASSIGNED if assignee else TaskStatus.OPEN).value,
            assigned_at=utc_now() if assignee else None,
        )
        self._tasks.add(task)
        return self._save(task)

    def update(self, task_id: uuid.UUID, data: TaskUpdate, *, own_staff_id: uuid.UUID | None = None) -> WorkflowTask:
        _require_all_scope(own_staff_id, "edit tasks")
        task = self._get(task_id, for_update=True)
        if task.status in _FINISHED:
            raise ConflictError(f"Task {task.id} is {task.status}; it can no longer be edited.")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(task, field, value)
        return self._save(task)

    def assign(self, task_id: uuid.UUID, data: TaskAssign, *, own_staff_id: uuid.UUID | None = None) -> WorkflowTask:
        _require_all_scope(own_staff_id, "assign tasks")
        task = self._get(task_id, for_update=True)
        if task.status in _REASSIGNABLE:
            if task.assigned_staff_id == data.staff_id:
                raise ConflictError(f"Task {task.id} is already assigned to this staff member.")
        else:
            ensure_transition(f"Task {task.id}", task.status, TaskStatus.ASSIGNED, TASK_TRANSITIONS)
            task.status = TaskStatus.ASSIGNED.value
        self._directory.active_staff(data.staff_id, "staff_id")
        task.assigned_staff_id = data.staff_id
        task.assigned_at = utc_now()
        return self._save(task)

    def start(self, task_id: uuid.UUID, *, own_staff_id: uuid.UUID | None = None) -> WorkflowTask:
        task = self._transition(task_id, TaskStatus.IN_PROGRESS, own_staff_id)
        task.started_at = now_not_before(task.assigned_at)
        return self._save(task)

    def complete(self, task_id: uuid.UUID, data: TaskComplete, *, own_staff_id: uuid.UUID | None = None) -> WorkflowTask:
        task = self._transition(task_id, TaskStatus.COMPLETED, own_staff_id)
        task.completed_at = now_not_before(task.started_at)
        task.completion_notes = data.completion_notes
        return self._save(task)

    def cancel(self, task_id: uuid.UUID, data: CancelRequest, *, own_staff_id: uuid.UUID | None = None) -> WorkflowTask:
        task = self._transition(task_id, TaskStatus.CANCELLED, own_staff_id)
        task.cancelled_at = utc_now()
        task.cancellation_reason = data.reason
        return self._save(task)

    def _transition(self, task_id: uuid.UUID, target: TaskStatus, own_staff_id: uuid.UUID | None) -> WorkflowTask:
        task = self._get(task_id, for_update=True, own_staff_id=own_staff_id)
        ensure_transition(f"Task {task.id}", task.status, target, TASK_TRANSITIONS)
        task.status = target.value
        return task

    def _save(self, task: WorkflowTask) -> WorkflowTask:
        self._session.commit()
        self._session.refresh(task)
        return task

    def _get(self, task_id: uuid.UUID, *, for_update: bool = False, own_staff_id: uuid.UUID | None = None) -> WorkflowTask:
        task = self._tasks.get(task_id, for_update=for_update)
        if task is None or (own_staff_id is not None and task.assigned_staff_id != own_staff_id):
            raise NotFoundError(f"Task {task_id} not found.")
        return task


def _require_all_scope(own_staff_id: uuid.UUID | None, action: str) -> None:
    if own_staff_id is not None:
        raise PermissionDeniedError(f"Your workflow permission is limited to your own tasks; you cannot {action}.")
