from functools import lru_cache
from typing import Literal
from uuid import UUID

from supabase import Client

from app.db import get_supabase_client
from app.models.entities import Message
from app.repositories.base import execute


class MessageRepository:
    def __init__(self, client: Client):
        self._client = client

    def add(
        self,
        conversation_id: UUID | str,
        role: Literal["user", "assistant"],
        content: str,
    ) -> Message:
        query = self._client.table("messages").insert(
            {"conversation_id": str(conversation_id), "role": role, "content": content}
        )
        return Message(**execute(query, idempotent=False).data[0])

    def list_recent(self, conversation_id: UUID | str, limit: int = 10) -> list[Message]:
        """The latest `limit` messages, oldest first (ready to feed into a prompt)."""
        query = (
            self._client.table("messages")
            .select("*")
            .eq("conversation_id", str(conversation_id))
            .order("created_at", desc=True)
            .limit(limit)
        )
        return [Message(**row) for row in reversed(execute(query).data)]


@lru_cache
def get_message_repository() -> MessageRepository:
    return MessageRepository(get_supabase_client())
