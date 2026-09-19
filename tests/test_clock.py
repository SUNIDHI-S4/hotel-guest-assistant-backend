from datetime import datetime, timezone

from app.clock import hotel_today


def test_hotel_today_uses_hotel_timezone_not_utc(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            # 20:00 UTC on the 18th is already 01:30 on the 19th in India (UTC+5:30).
            return datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr("app.clock.datetime", FrozenDatetime)

    assert hotel_today().isoformat() == "2026-09-19"
