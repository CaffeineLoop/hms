"""Translate domain and database exceptions into consistent JSON error responses.

Database error details are never returned to the client or logged verbatim:
driver messages can contain host names, user names or patient data.
"""

import logging
import traceback

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
)

from app.core.audit import request_context
from app.services.ai_service import AIServiceUnavailable
from app.core.errors import (
    AuthenticationError,
    BusinessValidationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
)

logger = logging.getLogger(__name__)


def _error(status_code: int, detail) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


async def _unauthenticated(request: Request, exc: AuthenticationError) -> JSONResponse:
    response = _error(status.HTTP_401_UNAUTHORIZED, exc.message)
    response.headers["WWW-Authenticate"] = "Bearer"
    return response


async def _forbidden(request: Request, exc: PermissionDeniedError) -> JSONResponse:
    return _error(status.HTTP_403_FORBIDDEN, exc.message)


async def _ai_unavailable(request: Request, exc: AIServiceUnavailable) -> JSONResponse:
    return _error(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


async def _rate_limited(request: Request, exc: RateLimitedError) -> JSONResponse:
    response = _error(status.HTTP_429_TOO_MANY_REQUESTS, exc.message)
    response.headers["Retry-After"] = str(exc.retry_after_seconds)
    return response


async def _request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Stage 6: FastAPI's default echoes the rejected `input` (and `ctx`) back to the client,
    which can reflect passwords or patient data into client logs. Keep only type/loc/msg."""
    errors = [
        {"type": e.get("type"), "loc": list(e.get("loc", ())), "msg": e.get("msg")} for e in exc.errors()
    ]
    return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, errors)


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Stage 6: never return stack traces or exception text. The log line carries the exception
    class, request id and the traceback frames, but not the exception message (it may embed
    SQL parameters or other patient data)."""
    request_id = getattr(request_context.get(), "request_id", None)
    frames = "".join(traceback.format_tb(exc.__traceback__)[-5:])
    logger.error("Unhandled %s on %s %s (request_id=%s)\n%s",
                 type(exc).__name__, request.method, request.url.path, request_id, frames)
    return _error(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error.")


async def _not_found(request: Request, exc: NotFoundError) -> JSONResponse:
    return _error(status.HTTP_404_NOT_FOUND, exc.message)


async def _conflict(request: Request, exc: ConflictError) -> JSONResponse:
    return _error(status.HTTP_409_CONFLICT, exc.message)


async def _business_validation(request: Request, exc: BusinessValidationError) -> JSONResponse:
    # Same shape as FastAPI's own request-validation errors.
    loc = ["body", exc.field] if exc.field else ["body"]
    return _error(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        [{"type": "value_error", "loc": loc, "msg": exc.message}],
    )


# Friendlier messages for uniqueness rules that PostgreSQL enforces. The services check
# these first; the database is the backstop for concurrent requests.
CONSTRAINT_MESSAGES = {
    "uq_patients_identity_phone": "A patient with the same name, date of birth and phone already exists.",
    "uq_patients_identity_email": "A patient with the same name, date of birth and email already exists.",
    "uq_allergies_active_substance": "The patient already has an active allergy to this substance.",
    "uq_lab_results_lab_order_id_analyte_code": "A result for this analyte already exists on the lab order.",
    "uq_departments_lower_name": "A department with this name already exists.",
    "uq_staff_employee_code": "This employee code is already in use.",
    "uq_staff_lower_email": "A staff member with this email already exists.",
    "uq_admissions_one_open_per_patient": "The patient already has an open admission.",
    "uq_users_username": "This username is already taken.",
    "uq_users_staff_id": "This staff member already has a user account.",
    "uq_roles_name": "A role with this name already exists.",
    "pk_user_roles": "The user already has this role.",
    "pk_role_permissions": "The role already has this permission.",
}


async def _integrity(request: Request, exc: IntegrityError) -> JSONResponse:
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    logger.warning("Integrity error on %s %s (constraint=%s)", request.method, request.url.path, constraint)
    message = CONSTRAINT_MESSAGES.get(constraint, "The request conflicts with existing data.")
    return _error(status.HTTP_409_CONFLICT, message)


async def _database(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.error("Database error on %s %s: %s", request.method, request.url.path, type(exc).__name__)
    connectivity = isinstance(exc, (OperationalError, InterfaceError)) or (
        isinstance(exc, DBAPIError) and exc.connection_invalidated
    )
    if connectivity:
        return _error(status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable. Please retry later.")
    return _error(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal database error.")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _request_validation)
    app.add_exception_handler(RateLimitedError, _rate_limited)
    app.add_exception_handler(AIServiceUnavailable, _ai_unavailable)
    app.add_exception_handler(Exception, _unhandled)
    app.add_exception_handler(AuthenticationError, _unauthenticated)
    app.add_exception_handler(PermissionDeniedError, _forbidden)
    app.add_exception_handler(NotFoundError, _not_found)
    app.add_exception_handler(ConflictError, _conflict)
    app.add_exception_handler(BusinessValidationError, _business_validation)
    app.add_exception_handler(IntegrityError, _integrity)
    app.add_exception_handler(SQLAlchemyError, _database)
