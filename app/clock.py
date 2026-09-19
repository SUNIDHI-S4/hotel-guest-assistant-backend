from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import get_settings


def hotel_today() -> date:
    """Today's date where the hotel is, regardless of the server's timezone."""
    return datetime.now(ZoneInfo(get_settings().hotel_timezone)).date()
