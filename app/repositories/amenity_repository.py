from functools import lru_cache
from uuid import UUID

from supabase import Client

from app.db import get_supabase_client
from app.models.entities import Amenity
from app.repositories.base import execute


class AmenityRepository:
    def __init__(self, client: Client):
        self._client = client

    def list_for_hotel(self, hotel_id: UUID | str) -> list[Amenity]:
        query = (
            self._client.table("amenities")
            .select("*")
            .eq("hotel_id", str(hotel_id))
            .order("name")
        )
        return [Amenity(**row) for row in execute(query).data]


@lru_cache
def get_amenity_repository() -> AmenityRepository:
    return AmenityRepository(get_supabase_client())
