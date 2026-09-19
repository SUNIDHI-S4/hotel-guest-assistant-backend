from datetime import date

from pydantic import BaseModel


class Slots(BaseModel):
    """The three details needed to search availability; None means not known yet."""

    check_in: date | None = None
    check_out: date | None = None
    guest_count: int | None = None

    @property
    def missing_fields(self) -> list[str]:
        return [name for name in ("check_in", "check_out", "guest_count") if getattr(self, name) is None]
