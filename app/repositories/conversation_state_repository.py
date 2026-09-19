from datetime import date, datetime, timezone
from functools import lru_cache
from uuid import UUID

from supabase import Client

from app.db import get_supabase_client
from app.models.entities import ConversationState
from app.repositories.base import execute


class ConversationStateRepository:
    def __init__(self, client: Client):
        self._client = client

    def get(self, conversation_id: UUID | str) -> ConversationState | None:
        query = (
            self._client.table("conversation_state")
            .select("*")
            .eq("conversation_id", str(conversation_id))
            .limit(1)
        )
        rows = execute(query).data
        return ConversationState(**rows[0]) if rows else None

    def save(
        self,
        conversation_id: UUID | str,
        check_in: date | None,
        check_out: date | None,
        guest_count: int | None,
    ) -> ConversationState:
        """Create or overwrite the slots for a conversation (None clears a slot)."""
        row = {
            "conversation_id": str(conversation_id),
            "check_in": check_in.isoformat() if check_in else None,
            "check_out": check_out.isoformat() if check_out else None,
            "guest_count": guest_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        query = self._client.table("conversation_state").upsert(
            row, on_conflict="conversation_id"
        )
        return ConversationState(**execute(query).data[0])

    def reset(self, conversation_id: UUID | str) -> ConversationState:
        """Clear all slots, e.g. after an availability search has been answered."""
        return self.save(conversation_id, None, None, None)


@lru_cache
def get_conversation_state_repository() -> ConversationStateRepository:
    return ConversationStateRepository(get_supabase_client())
