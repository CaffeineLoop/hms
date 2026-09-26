"""Data access for infrastructure health checks."""

from alembic.runtime.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.orm import Session


class HealthRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def ping(self) -> bool:
        """Round-trip a trivial query to PostgreSQL."""
        return self._session.execute(text("SELECT 1")).scalar_one() == 1

    def current_migration_revision(self) -> str | None:
        """Alembic revision recorded in the database (None if never migrated)."""
        connection = self._session.connection()
        return MigrationContext.configure(connection).get_current_revision()
