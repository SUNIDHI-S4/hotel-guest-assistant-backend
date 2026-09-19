from functools import lru_cache
from uuid import UUID

from supabase import Client

from app.db import get_supabase_client
from app.models.entities import Hotel
from app.repositories.base import execute


class HotelRepository:
    def __init__(self, client: Client):
        self._client = client

    def get(self, hotel_id: UUID | str) -> Hotel | None:
        query = self._client.table("hotels").select("*").eq("id", str(hotel_id)).limit(1)
        rows = execute(query).data
        return Hotel(**rows[0]) if rows else None


@lru_cache
def get_hotel_repository() -> HotelRepository:
    return HotelRepository(get_supabase_client())
