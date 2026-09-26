"""Pre-flight: time handling never depends on the host machine's local time zone."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core import clock
from app.core.config import ConfigurationError, load_settings

DB = "postgresql+psycopg://hms_app:change-me@127.0.0.1:1/hms_dev"


@pytest.fixture(autouse=True)
def restore_facility_zone():
    yield
    clock.configure_facility_timezone("UTC")


def test_utc_now_is_timezone_aware_utc():
    now = clock.utc_now()
    assert now.tzinfo is UTC
    assert abs(now - datetime.now(UTC)) < timedelta(seconds=5)


def test_facility_today_follows_configured_zone_not_host(monkeypatch):
    fixed = datetime(2026, 3, 1, 22, 30, tzinfo=UTC)  # already 2 March in Nairobi (UTC+3)
    monkeypatch.setattr(clock, "utc_now", lambda: fixed)
    clock.configure_facility_timezone("UTC")
    assert clock.facility_today().isoformat() == "2026-03-01"
    clock.configure_facility_timezone("Africa/Nairobi")
    assert clock.facility_today().isoformat() == "2026-03-02"
    clock.configure_facility_timezone("America/Los_Angeles")
    assert clock.facility_today().isoformat() == "2026-03-01"
    assert clock.facility_timezone() == ZoneInfo("America/Los_Angeles")


def test_latest_allowed_instant_is_now_plus_skew(monkeypatch):
    fixed = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(clock, "utc_now", lambda: fixed)
    assert clock.latest_allowed_instant() == fixed + clock.MAX_CLOCK_SKEW


def test_app_timezone_defaults_to_utc(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB)
    monkeypatch.delenv("APP_TIMEZONE", raising=False)
    assert load_settings(_env_file=None).app_timezone == "UTC"


def test_app_timezone_accepts_iana_names(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB)
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Kolkata")
    assert load_settings(_env_file=None).app_timezone == "Asia/Kolkata"


@pytest.mark.parametrize("value", ["Mars/Olympus", "+05:30", "", "../etc/passwd"])
def test_invalid_app_timezone_fails_clearly(monkeypatch, value):
    monkeypatch.setenv("DATABASE_URL", DB)
    monkeypatch.setenv("APP_TIMEZONE", value)
    with pytest.raises(ConfigurationError, match="APP_TIMEZONE"):
        load_settings(_env_file=None)


def test_create_app_configures_facility_zone(monkeypatch):
    from app.factory import create_app

    monkeypatch.setenv("DATABASE_URL", DB)
    monkeypatch.setenv("APP_TIMEZONE", "Africa/Nairobi")
    create_app(load_settings(_env_file=None))
    assert clock.facility_timezone() == ZoneInfo("Africa/Nairobi")

