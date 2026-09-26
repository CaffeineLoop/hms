"""Application configuration.

All configuration comes from environment variables (optionally loaded from a
local, git-ignored `.env` file). No secret has a default value in code: if a
required variable is missing, startup fails with a `ConfigurationError` that
names the missing variable.
"""

from enum import StrEnum
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

REQUIRED_DRIVER = "postgresql+psycopg"


class ConfigurationError(RuntimeError):
    """Raised when the application configuration is missing or invalid."""


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


def _validate_database_url(value: SecretStr | None, variable: str) -> SecretStr | None:
    if value is None:
        return None
    raw = value.get_secret_value()
    try:
        url = make_url(raw)
    except Exception as exc:  # sqlalchemy raises ArgumentError for bad URLs
        raise ValueError(f"{variable} is not a valid database URL") from exc
    if url.drivername != REQUIRED_DRIVER:
        raise ValueError(
            f"{variable} must use the '{REQUIRED_DRIVER}://' driver (psycopg 3), "
            f"got '{url.drivername}://'"
        )
    if not url.database:
        raise ValueError(f"{variable} must include a database name")
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Hospital Management System"
    app_env: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"

    # Required. SecretStr keeps the password out of repr()/logs.
    database_url: SecretStr
    # Optional for running the app; required by the integration test suite.
    test_database_url: SecretStr | None = None

    db_connect_timeout: int = Field(default=5, ge=1, le=60)

    # Lifetime of a login session / bearer token (Stage 5). Tokens are opaque random values;
    # only their SHA-256 is stored, so no signing secret is needed.
    auth_token_ttl_minutes: int = Field(default=480, ge=5, le=1440)
    # Stage 6: a session unused for this long is revoked (idle timeout).
    auth_idle_timeout_minutes: int = Field(default=30, ge=5, le=480)
    # Stage 6 login abuse protection (counted from audited login failures).
    login_max_failures_per_user: int = Field(default=5, ge=1, le=100)
    login_max_failures_per_ip: int = Field(default=20, ge=1, le=100_000)
    login_lockout_minutes: int = Field(default=15, ge=1, le=1440)

    # --- Stage 7: AI assistant (read-only clinical analysis) ---------------------------------
    # Provider registry key: "gemini" (default), "fake" (deterministic, offline; tests/dev) or
    # "disabled". The model id and key are configuration only - never hard-coded in logic.
    llm_provider: str = "gemini"
    llm_model: str = "gemini-3.8-flash"
    gemini_api_key: SecretStr | None = None
    llm_temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    llm_timeout_seconds: int = Field(default=30, ge=5, le=300)
    llm_max_output_tokens: int = Field(default=2048, ge=256, le=16384)
    ai_max_items_per_tool: int = Field(default=50, ge=1, le=500)
    # Third-party tracing (e.g. LangSmith) would send patient data off-site; off unless allowed.
    ai_allow_external_tracing: bool = False

    @field_validator("llm_provider")
    @classmethod
    def _check_llm_provider(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"gemini", "fake", "disabled"}:
            raise ValueError("must be one of: gemini, fake, disabled")
        return value

    # IANA zone used for calendar-date rules (e.g. date of birth not in the future).
    # Timestamps are always stored and returned in UTC regardless of this value.
    app_timezone: str = "UTC"

    @field_validator("app_timezone")
    @classmethod
    def _check_app_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"'{value}' is not a valid IANA time zone (e.g. 'UTC', 'Africa/Nairobi')")
        return value

    @field_validator("database_url")
    @classmethod
    def _check_database_url(cls, value: SecretStr) -> SecretStr:
        return _validate_database_url(value, "DATABASE_URL")

    @field_validator("test_database_url")
    @classmethod
    def _check_test_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        return _validate_database_url(value, "TEST_DATABASE_URL")

    @property
    def database_url_parsed(self) -> URL:
        return make_url(self.database_url.get_secret_value())


def load_settings(**overrides) -> Settings:
    """Build settings, converting validation errors into a readable ConfigurationError."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]).upper() or "<settings>"
            if error["type"] == "missing":
                problems.append(f"  - {field}: required environment variable is not set")
            else:
                problems.append(f"  - {field}: {error['msg']}")
        raise ConfigurationError(
            "Invalid HMS configuration:\n"
            + "\n".join(problems)
            + "\nSee .env.example for the expected variables."
        ) from None


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings instance (cached)."""
    return load_settings()
