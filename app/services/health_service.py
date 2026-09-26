"""Business logic for liveness and database-connectivity checks."""

import logging
import time
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories.health_repository import HealthRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatabaseStatus:
    reachable: bool
    latency_ms: float | None = None
    migration_revision: str | None = None


class HealthService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def liveness(self) -> dict[str, str]:
        return {
            "status": "ok",
            "app": self._settings.app_name,
            "environment": self._settings.app_env.value,
        }

    def check_database(self, session: Session) -> DatabaseStatus:
        repository = HealthRepository(session)
        started = time.perf_counter()
        try:
            repository.ping()
            revision = repository.current_migration_revision()
        except SQLAlchemyError as exc:
            # Log the exception class only: driver messages can include host/user details.
            logger.error("Database health check failed: %s", type(exc).__name__)
            return DatabaseStatus(reachable=False)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return DatabaseStatus(reachable=True, latency_ms=latency_ms, migration_revision=revision)
