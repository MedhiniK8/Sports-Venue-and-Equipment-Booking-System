from datetime import datetime
from zoneinfo import ZoneInfo


VENUE_TIMEZONE = ZoneInfo("Asia/Kolkata")


def current_venue_local_naive() -> datetime:
    return datetime.now(VENUE_TIMEZONE).replace(tzinfo=None)


def normalize_venue_local_naive(value: datetime) -> datetime:
    if value.utcoffset() is None:
        return value
    return value.astimezone(VENUE_TIMEZONE).replace(tzinfo=None)
