from datetime import date
from uuid import UUID

from pydantic import BaseModel


class AvailableRoom(BaseModel):
    room_type_id: UUID
    name: str
    description: str | None = None
    max_guests: int
    price_per_night: float
    total_price: float
    breakfast_included: bool
    rooms_available: int


class AvailabilityResult(BaseModel):
    check_in: date
    check_out: date
    guest_count: int
    nights: int
    # Smallest suitable room first; empty when nothing fits or everything is booked.
    rooms: list[AvailableRoom]
    # Tells the two empty cases apart: True when no single room type sleeps this many guests.
    party_too_large: bool = False
