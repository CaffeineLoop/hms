"""Test-database isolation rules shared by the test suite.

The suite must never run against the development database. These checks run
before any database fixture is created; a violation aborts the whole run.
"""

from sqlalchemy.engine import make_url

from app.core.config import Environment, Settings
from app.core.principal import Principal

TEST_DB_SUFFIX = "_test"


class UnsafeTestDatabaseError(RuntimeError):
    pass


def assert_test_database_is_isolated(database_url: str, test_database_url: str | None) -> None:
    if not test_database_url:
        raise UnsafeTestDatabaseError(
            "TEST_DATABASE_URL is not set; refusing to run database tests."
        )
    dev = make_url(database_url)
    test = make_url(test_database_url)
    if not (test.database or "").endswith(TEST_DB_SUFFIX):
        raise UnsafeTestDatabaseError(
            f"Test database name must end with '{TEST_DB_SUFFIX}' (got '{test.database}')."
        )
    same_server = (dev.host, dev.port or 5432) == (test.host, test.port or 5432)
    if same_server and dev.database == test.database:
        raise UnsafeTestDatabaseError("TEST_DATABASE_URL points at the DATABASE_URL database.")


def build_test_settings(settings: Settings) -> Settings:
    """Copy of `settings` whose primary database is the isolated test database."""
    test_url = settings.test_database_url.get_secret_value() if settings.test_database_url else None
    assert_test_database_is_isolated(settings.database_url.get_secret_value(), test_url)
    return settings.model_copy(
        update={"database_url": settings.test_database_url, "app_env": Environment.TEST}
    )


# Stage 5: Stage 1-4 domain tests run as this explicit full-access principal (injected by the
# `client` fixture). Authentication and authorization themselves are tested with real users,
# real roles and real bearer tokens through the `auth_client` fixture.
FULL_ACCESS = Principal(user_id=None, staff_id=None, username="test-full-access", is_superuser=True)
