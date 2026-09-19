from datetime import date
from functools import lru_cache
from uuid import UUID

from supabase import Client

from app.db import get_supabase_client
from app.models.entities import Booking
from app.repositories.base import execute


class BookingRepository:
    def __init__(self, client: Client):
        self._client = client

    def list_overlapping(
        self, hotel_id: UUID | str, check_in: date, check_out: date
    ) -> list[Booking]:
        """Bookings that hold rooms during [check_in, check_out).

        A booking overlaps when booking.check_in < requested check_out AND
        booking.check_out > requested check_in, so same-day turnover is not a clash.
        Cancelled bookings are ignored; any other status still holds the room.
        """
        query = (
            self._client.table("bookings")
            .select("*")
            .eq("hotel_id", str(hotel_id))
            .neq("booking_status", "cancelled")
            .lt("check_in_date", check_out.isoformat())
            .gt("check_out_date", check_in.isoformat())
        )
        return [Booking(**row) for row in execute(query).data]


@lru_cache
def get_booking_repository() -> BookingRepository:
    return BookingRepository(get_supabase_client())
