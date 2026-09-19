from functools import lru_cache
from uuid import UUID

from supabase import Client

from app.db import get_supabase_client
from app.repositories.base import execute


class ConversationRepository:
    def __init__(self, client: Client):
        self._client = client

    def create(self, hotel_id: str) -> str:
        """Insert a new conversation for the hotel and return its id."""
        query = self._client.table("conversations").insert({"hotel_id": hotel_id})
        return execute(query, idempotent=False).data[0]["id"]

    def exists(self, conversation_id: UUID | str) -> bool:
        query = (
            self._client.table("conversations")
            .select("id")
            .eq("id", str(conversation_id))
            .limit(1)
        )
        return bool(execute(query).data)


@lru_cache
def get_conversation_repository() -> ConversationRepository:
    return ConversationRepository(get_supabase_client())
