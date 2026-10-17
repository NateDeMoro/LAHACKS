from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

LA = ZoneInfo("America/Los_Angeles")
# Fixed anchor for fixture replays: eICU offset 0 maps here (PDT, -07:00)
FIXTURE_START = datetime(2026, 10, 18, 9, 0, tzinfo=LA)


def now_la() -> datetime:
    return datetime.now(LA)


def parse_ts(s: str) -> datetime:
    """Parse an ISO timestamp with offset into LA time. Rejects naive input."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError("timestamp must include a UTC offset")
    return dt.astimezone(LA)


def offset_to_ts(minutes: float) -> datetime:
    return FIXTURE_START + timedelta(minutes=minutes)
