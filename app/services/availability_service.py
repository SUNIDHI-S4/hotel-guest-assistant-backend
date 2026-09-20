from collections import Counter
from collections.abc import Callable
from datetime import date
from functools import lru_cache

from app.clock import hotel_today
from app.config import get_settings
from app.exceptions import InvalidAvailabilityRequest
from app.models.availability import AvailabilityResult, AvailableRoom
from app.repositories.booking_repository import BookingRepository, get_booking_repository
from app.repositories.room_type_repository import RoomTypeRepository, get_room_type_repository


class AvailabilityService:
    """Deterministic room availability; no LLM involved."""

    def __init__(
        self,
        hotel_id: str,
        room_types: RoomTypeRepository,
        bookings: BookingRepository,
        today: Callable[[], date] = hotel_today,
    ):
        self._hotel_id = hotel_id
        self._room_types = room_types
        self._bookings = bookings
        self._today = today

    def check(self, check_in: date, check_out: date, guest_count: int) -> AvailabilityResult:
        self._validate(check_in, check_out, guest_count)
        nights = (check_out - check_in).days

        candidates = self._room_types.list_for_capacity(self._hotel_id, guest_count)
        rooms: list[AvailableRoom] = []

        if candidates:
            overlapping = Counter(
                booking.room_type_id
                for booking in self._bookings.list_overlapping(self._hotel_id, check_in, check_out)
            )
            # Candidates arrive smallest-first, so the output keeps that recommendation order.
            for room in candidates:
                remaining = room.total_rooms - overlapping[room.id]
                if remaining > 0:
                    rooms.append(
                        AvailableRoom(
                            room_type_id=room.id,
                            name=room.name,
                            description=room.description,
                            max_guests=room.max_guests,
                            price_per_night=room.price_per_night,
                            total_price=round(room.price_per_night * nights, 2),
                            breakfast_included=room.breakfast_included,
                            rooms_available=remaining,
                        )
                    )

        return AvailabilityResult(
            check_in=check_in,
            check_out=check_out,
            guest_count=guest_count,
            nights=nights,
            rooms=rooms,
            party_too_large=not candidates,
        )

    def _validate(self, check_in: date, check_out: date, guest_count: int) -> None:
        if guest_count <= 0:
            raise InvalidAvailabilityRequest("The number of guests must be at least 1.", "guest_count")
        if check_in < self._today():
            raise InvalidAvailabilityRequest("The check-in date can't be in the past.", "check_in")
        if check_out <= check_in:
            raise InvalidAvailabilityRequest(
                "The check-out date must be after the check-in date.", "check_out"
            )


@lru_cache
def get_availability_service() -> AvailabilityService:
    return AvailabilityService(
        get_settings().default_hotel_id,
        get_room_type_repository(),
        get_booking_repository(),
    )
