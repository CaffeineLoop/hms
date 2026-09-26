"""Authenticated authorship binding (Stage 6).

For a normal human request the person who records something is the authenticated user's
staff member - never a client-supplied identity:

    authenticated user -> linked staff -> author / recorder / requester / approver

`bind_actor()` is applied by routers to the request body before calling the service:
- supplying another staff member's id is an impersonation attempt -> 403;
- supplying a free-text name is rejected -> 403 (the name snapshot is derived from staff);
- otherwise the actor field is set to the caller's staff id.
Principals without a staff member (system/import principals, e.g. a future importer, and
the test suite's full-access principal) keep the Stage 4 explicit-identity behaviour so
historical free-text records remain possible where genuinely required.

Assignment fields (encounter attending clinician, appointment clinician, task assignee,
admission attending) are NOT authorship and remain client-chosen.
"""

from pydantic import BaseModel

from app.core.errors import PermissionDeniedError
from app.core.principal import Principal


def bind_actor[M: BaseModel](data: M, principal: Principal, staff_field: str, name_field: str | None = None) -> M:
    if principal.staff_id is None:
        return data
    claimed = getattr(data, staff_field)
    if claimed is not None and claimed != principal.staff_id:
        raise PermissionDeniedError(
            f"{staff_field} must be your own staff member; you cannot record on behalf of another staff member."
        )
    if name_field is not None and getattr(data, name_field) is not None:
        raise PermissionDeniedError(
            f"{name_field} cannot be supplied: the recorded person is the authenticated user."
        )
    update = {staff_field: principal.staff_id}
    if name_field is not None:
        update[name_field] = None
    return data.model_copy(update=update)
