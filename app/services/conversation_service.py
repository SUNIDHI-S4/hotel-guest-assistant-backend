from functools import lru_cache
from typing import Literal
from uuid import UUID

from app.config import get_settings
from app.exceptions import ConversationNotFound
from app.models.entities import Message
from app.models.slots import Slots
from app.repositories.conversation_repository import (
    ConversationRepository,
    get_conversation_repository,
)
from app.repositories.conversation_state_repository import (
    ConversationStateRepository,
    get_conversation_state_repository,
)
from app.repositories.message_repository import MessageRepository, get_message_repository

DEFAULT_HISTORY_LIMIT = 100


class ConversationService:
    """Conversations, their message history and the availability slots gathered so far."""

    def __init__(
        self,
        hotel_id: str,
        conversations: ConversationRepository,
        messages: MessageRepository,
        states: ConversationStateRepository,
    ):
        self._hotel_id = hotel_id
        self._conversations = conversations
        self._messages = messages
        self._states = states

    def create(self) -> str:
        return self._conversations.create(self._hotel_id)

    def require_exists(self, conversation_id: UUID) -> None:
        if not self._conversations.exists(conversation_id):
            raise ConversationNotFound()

    # --- messages ----------------------------------------------------------------------------

    def add_message(
        self, conversation_id: UUID, role: Literal["user", "assistant"], content: str
    ) -> Message:
        return self._messages.add(conversation_id, role, content)

    def get_messages(
        self, conversation_id: UUID, limit: int = DEFAULT_HISTORY_LIMIT
    ) -> list[Message]:
        """The latest `limit` messages, oldest first. Unknown conversations raise, not return []."""
        self.require_exists(conversation_id)
        return self.history(conversation_id, limit)

    def history(self, conversation_id: UUID, limit: int = DEFAULT_HISTORY_LIMIT) -> list[Message]:
        """Like get_messages, for callers that have already checked the conversation exists."""
        return self._messages.list_recent(conversation_id, limit)

    # --- availability slots ------------------------------------------------------------------

    def get_slots(self, conversation_id: UUID) -> Slots:
        state = self._states.get(conversation_id)
        if state is None:
            return Slots()
        return Slots(
            check_in=state.check_in, check_out=state.check_out, guest_count=state.guest_count
        )

    def update_slots(
        self, conversation_id: UUID, extracted: Slots, current: Slots | None = None
    ) -> Slots:
        """Merge slots found in a new message into the saved ones and persist the result.

        Newly extracted values win; anything not mentioned is kept. Pass `current` if the
        caller has just read it, to save a database round trip.
        """
        current = current if current is not None else self.get_slots(conversation_id)
        merged = Slots(
            check_in=extracted.check_in or current.check_in,
            check_out=extracted.check_out or current.check_out,
            guest_count=(
                extracted.guest_count if extracted.guest_count is not None else current.guest_count
            ),
        )

        # A later check-in than the saved check-out means a new stay; asking for a fresh
        # check-out is friendlier than reporting that the old one is now invalid.
        if (
            extracted.check_in
            and not extracted.check_out
            and current.check_out
            and current.check_out <= extracted.check_in
        ):
            merged.check_out = None

        if merged != current:
            self._states.save(
                conversation_id, merged.check_in, merged.check_out, merged.guest_count
            )
        return merged

    def clear_slot(self, conversation_id: UUID, slots: Slots, field: str) -> Slots:
        """Forget one slot (e.g. a check-in that turned out to be in the past) and persist it."""
        cleared = slots.model_copy(update={field: None})
        self._states.save(
            conversation_id, cleared.check_in, cleared.check_out, cleared.guest_count
        )
        return cleared


@lru_cache
def get_conversation_service() -> ConversationService:
    return ConversationService(
        get_settings().default_hotel_id,
        get_conversation_repository(),
        get_message_repository(),
        get_conversation_state_repository(),
    )
