"""Health endpoints.

GET /health     — liveness: the process is up. Never touches the database.
GET /health/db  — readiness: PostgreSQL is reachable. 503 when it is not.
"""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.health import DatabaseHealthResponse, HealthResponse
from app.services.health_service import HealthService

router = APIRouter(prefix="/health", tags=["health"])


def get_health_service(request: Request) -> HealthService:
    return HealthService(request.app.state.settings)


@router.get("", response_model=HealthResponse)
def health(service: HealthService = Depends(get_health_service)) -> HealthResponse:
    return HealthResponse(**service.liveness())


@router.get(
    "/db",
    response_model=DatabaseHealthResponse,
    responses={503: {"model": DatabaseHealthResponse, "description": "Database unreachable"}},
)
def database_health(
    response: Response,
    service: HealthService = Depends(get_health_service),
    session: Session = Depends(get_db),
) -> DatabaseHealthResponse:
    result = service.check_database(session)
    if not result.reachable:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return DatabaseHealthResponse(status="unavailable", database="unreachable")
    return DatabaseHealthResponse(
        status="ok",
        database="reachable",
        latency_ms=result.latency_ms,
        migration_revision=result.migration_revision,
    )
