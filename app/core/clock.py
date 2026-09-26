"""The single source of "now" for the application.

- Instants are always timezone-aware UTC (`utc_now()`); nothing reads the host's local clock zone.
- Calendar dates (e.g. "is this date of birth in the future?") are evaluated in the
  facility's configured IANA time zone (`APP_TIMEZONE`, default UTC), set once by the
  application factory. This keeps results identical on any machine.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

# Tolerated difference between client and server clocks for "not in the future" checks.
MAX_CLOCK_SKEW = timedelta(minutes=5)

_facility_zone: ZoneInfo = ZoneInfo("UTC")


def configure_facility_timezone(name: str) -> None:
    global _facility_zone
    _facility_zone = ZoneInfo(name)


def facility_timezone() -> ZoneInfo:
    return _facility_zone


def utc_now() -> datetime:
    return datetime.now(UTC)


def facility_today() -> date:
    """Today's calendar date at the facility."""
    return utc_now().astimezone(_facility_zone).date()


def now_not_before(earliest: datetime | None) -> datetime:
    """'now', but never earlier than `earliest`.

    Used when a workflow step (verify, release, activate, ...) is stamped with the current
    time but must not precede an earlier step whose timestamp came from a client clock
    that may be slightly ahead (see MAX_CLOCK_SKEW).
    """
    now = utc_now()
    return max(now, earliest) if earliest is not None else now


def latest_allowed_instant() -> datetime:
    """Clinical timestamps may not be later than this."""
    return utc_now() + MAX_CLOCK_SKEW
