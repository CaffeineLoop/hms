"""Command-line database connectivity check.

    python -m app.db.check

Exits 0 if PostgreSQL is reachable with the configured DATABASE_URL, 1 if not,
2 if the configuration itself is invalid. Uses the same service as GET /health/db.
"""

import sys

from app.core.config import ConfigurationError, get_settings
from app.db.session import build_engine, build_session_factory
from app.services.health_service import HealthService


def main() -> int:
    try:
        settings = get_settings()
    except ConfigurationError as exc:
        print(exc, file=sys.stderr)
        return 2

    engine = build_engine(settings)
    url = settings.database_url_parsed
    target = f"{url.host}:{url.port or 5432}/{url.database}"
    try:
        with build_session_factory(engine)() as session:
            result = HealthService(settings).check_database(session)
    finally:
        engine.dispose()

    if not result.reachable:
        print(f"Database UNREACHABLE: {target}", file=sys.stderr)
        return 1
    print(
        f"Database OK: {target} "
        f"(latency {result.latency_ms} ms, migration revision {result.migration_revision})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
