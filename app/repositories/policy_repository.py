from functools import lru_cache
from uuid import UUID

from supabase import Client

from app.db import get_supabase_client
from app.models.entities import Policy
from app.repositories.base import execute


class PolicyRepository:
    def __init__(self, client: Client):
        self._client = client

    def list_for_hotel(self, hotel_id: UUID | str) -> list[Policy]:
        query = (
            self._client.table("policies")
            .select("*")
            .eq("hotel_id", str(hotel_id))
            .order("policy_type")
        )
        return [Policy(**row) for row in execute(query).data]


@lru_cache
def get_policy_repository() -> PolicyRepository:
    return PolicyRepository(get_supabase_client())
