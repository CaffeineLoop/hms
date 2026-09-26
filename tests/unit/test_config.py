"""Configuration loads from the environment and fails clearly when invalid."""

import pytest

from app.core.config import ConfigurationError, Environment, load_settings

VALID_URL = "postgresql+psycopg://hms_app:change-me@db.example:5433/hms_dev"
CONFIG_VARS = [
    "DATABASE_URL",
    "TEST_DATABASE_URL",
    "APP_ENV",
    "APP_NAME",
    "LOG_LEVEL",
    "DB_CONNECT_TIMEOUT",
]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Start every test from an empty configuration environment."""
    for name in CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)


def load(**overrides):
    # _env_file=None: ignore the developer's local .env so tests see only the variables they set.
    return load_settings(_env_file=None, **overrides)


def test_loads_values_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_NAME", "HMS Under Test")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "7")

    settings = load()

    assert settings.database_url.get_secret_value() == VALID_URL
    assert settings.app_env is Environment.TEST
    assert settings.app_name == "HMS Under Test"
    assert settings.db_connect_timeout == 7
    url = settings.database_url_parsed
    assert (url.host, url.port, url.database, url.username) == ("db.example", 5433, "hms_dev", "hms_app")


def test_defaults_apply_for_optional_values(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    settings = load()
    assert settings.app_env is Environment.DEVELOPMENT
    assert settings.db_connect_timeout == 5
    assert settings.test_database_url is None


def test_missing_database_url_fails_clearly():
    with pytest.raises(ConfigurationError) as excinfo:
        load()
    message = str(excinfo.value)
    assert "DATABASE_URL" in message
    assert "required environment variable is not set" in message
    assert ".env.example" in message


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql+psycopg2://u:change-me@localhost/hms_dev", "psycopg 3"),
        ("postgresql://u:change-me@localhost/hms_dev", "psycopg 3"),
        ("sqlite:///hms.db", "psycopg 3"),
        ("postgresql+psycopg://u:change-me@localhost", "database name"),
        ("not a url", "not a valid database URL"),
    ],
)
def test_invalid_database_url_fails_clearly(monkeypatch, url, expected):
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ConfigurationError) as excinfo:
        load()
    assert "DATABASE_URL" in str(excinfo.value)
    assert expected in str(excinfo.value)


def test_invalid_test_database_url_fails_clearly(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv("TEST_DATABASE_URL", "mysql://u:change-me@localhost/hms_test")
    with pytest.raises(ConfigurationError, match="TEST_DATABASE_URL"):
        load()


def test_invalid_environment_name_fails_clearly(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv("APP_ENV", "staging-ish")
    with pytest.raises(ConfigurationError, match="APP_ENV"):
        load()


@pytest.mark.parametrize("value", ["0", "61", "abc"])
def test_out_of_range_connect_timeout_fails(monkeypatch, value):
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", value)
    with pytest.raises(ConfigurationError, match="DB_CONNECT_TIMEOUT"):
        load()


def test_password_is_not_exposed_in_repr_or_str(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://hms_app:change-me@localhost/hms_dev")
    settings = load()
    assert "change-me" not in repr(settings)
    assert "change-me" not in str(settings)
    assert "change-me" not in settings.model_dump_json()
