from functools import lru_cache
from uuid import UUID

from supabase import Client

from app.db import get_supabase_client
from app.models.entities import RoomType
from app.repositories.base import execute


class RoomTypeRepository:
    def __init__(self, client: Client):
        self._client = client

    def list_for_hotel(self, hotel_id: UUID | str) -> list[RoomType]:
        """All room types, smallest first."""
        query = self._base_query(hotel_id)
        return [RoomType(**row) for row in execute(query).data]

    def list_for_capacity(self, hotel_id: UUID | str, guest_count: int) -> list[RoomType]:
        """Room types that fit the party (max_guests >= guest_count), smallest first."""
        query = self._base_query(hotel_id).gte("max_guests", guest_count)
        return [RoomType(**row) for row in execute(query).data]

    def _base_query(self, hotel_id: UUID | str):
        return (
            self._client.table("room_types")
            .select("*")
            .eq("hotel_id", str(hotel_id))
            .order("max_guests")
            .order("price_per_night")
        )


@lru_cache
def get_room_type_repository() -> RoomTypeRepository:
    return RoomTypeRepository(get_supabase_client())
