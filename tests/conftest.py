"""Shared fixtures.

Unit tests (tests/unit) need no database. Integration tests (tests/integration)
use ONLY the database named by TEST_DATABASE_URL; the isolation guard in
tests/support.py aborts the run before any connection is made if that database
is missing or could be the development database.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api.auth import get_principal
from app.core.config import ConfigurationError, Settings, load_settings
from app.db.session import build_engine
from app.factory import create_app
from tests.support import FULL_ACCESS, UnsafeTestDatabaseError, build_test_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def make_alembic_config(database_url: str, script_location: Path | None = None) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    if script_location is not None:
        config.set_main_option("script_location", str(script_location))
    # Passed via attributes (not the ini) so no URL/password is ever written to config text.
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    try:
        settings = load_settings()
        return build_test_settings(settings).model_copy(update={"login_max_failures_per_ip": 100_000})
    except (ConfigurationError, UnsafeTestDatabaseError) as exc:
        pytest.exit(f"Refusing to run database tests: {exc}", returncode=3)


@pytest.fixture(scope="session")
def test_database_url(test_settings: Settings) -> str:
    return test_settings.database_url.get_secret_value()


@pytest.fixture(scope="session")
def alembic_config(test_database_url: str) -> Config:
    return make_alembic_config(test_database_url)


@pytest.fixture(scope="session")
def migrated_database(alembic_config: Config) -> Iterator[None]:
    """Test database migrated to head for the whole session."""
    command.upgrade(alembic_config, "head")
    yield


@pytest.fixture(scope="session")
def test_engine(test_settings: Settings, migrated_database: None) -> Iterator[Engine]:
    engine = build_engine(test_settings)
    yield engine
    engine.dispose()


# The apps hold no per-test state, so they are built once per session (building a FastAPI app
# and compiling its ~120 routes on first request is the dominant per-test cost otherwise).
@pytest.fixture(scope="session")
def full_access_app(test_settings: Settings, migrated_database: None):
    app = create_app(test_settings)
    app.dependency_overrides[get_principal] = lambda: FULL_ACCESS
    return app


@pytest.fixture(scope="session")
def real_auth_app(test_settings: Settings, migrated_database: None):
    return create_app(test_settings)


@pytest.fixture
def client(full_access_app) -> Iterator[TestClient]:
    """App bound to the test database, called as a full-access principal (see FULL_ACCESS)."""
    with TestClient(full_access_app) as test_client:
        yield test_client


@pytest.fixture
def auth_client(real_auth_app) -> Iterator[TestClient]:
    """App bound to the test database with REAL authentication (no overrides)."""
    with TestClient(real_auth_app) as test_client:
        yield test_client
