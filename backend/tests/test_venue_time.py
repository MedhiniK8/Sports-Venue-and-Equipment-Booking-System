from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app import venue_time
from app.venue_time import normalize_venue_local_naive


def test_venue_timezone_is_the_standard_asia_kolkata_zone():
    assert venue_time.VENUE_TIMEZONE == ZoneInfo("Asia/Kolkata")


def test_aware_datetime_is_converted_to_venue_local_naive():
    utc_value = datetime(2026, 11, 25, 8, 58, tzinfo=timezone.utc)

    assert normalize_venue_local_naive(utc_value) == datetime(
        2026, 11, 25, 14, 28
    )


def test_naive_datetime_is_already_venue_local():
    local_value = datetime(2026, 11, 25, 14, 28)

    assert normalize_venue_local_naive(local_value) is local_value


def test_current_venue_time_uses_zoneinfo_and_returns_naive_local_value(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz == ZoneInfo("Asia/Kolkata")
            utc_value = datetime(2026, 11, 25, 8, 58, tzinfo=timezone.utc)
            return utc_value.astimezone(tz)

    monkeypatch.setattr(venue_time, "datetime", FixedDateTime)

    result = venue_time.current_venue_local_naive()

    assert result == datetime(2026, 11, 25, 14, 28)
    assert result.tzinfo is None
