import logging
import time
from functools import lru_cache
from uuid import UUID

from app.config import get_settings
from app.exceptions import InvalidAvailabilityRequest
from app.models.chat import (
    AvailabilityChatResponse,
    ChatResponse,
    SlotCollectionChatResponse,
    TextChatResponse,
)
from app.models.slots import Slots
from app.services.availability_service import AvailabilityService, get_availability_service
from app.services.chat_messages import (
    availability_message,
    history_text,
    invalid_slot_message,
    slot_collection_message,
)
from app.services.conversation_service import ConversationService, get_conversation_service
from app.services.gemini_service import GeminiService, get_gemini_service
from app.services.intent_service import IntentService, get_intent_service
from app.services.prompt_builder import PromptBuilder, get_prompt_builder
from app.services.retrieval_service import RetrievalService, get_retrieval_service
from app.services.slot_extraction_service import (
    SlotExtractionService,
    get_slot_extraction_service,
)

logger = logging.getLogger(__name__)


class ChatService:
    """One chat turn, end to end.

    A message is either a room search or a question about the hotel:

      availability -> collect check-in / check-out / guests -> deterministic availability engine
      knowledge    -> retrieve hotel facts -> grounded prompt -> Gemini

    A turn is saved to the history only once it has produced an answer, so a failed turn
    leaves nothing behind and the guest can simply send the message again.
    """

    def __init__(
        self,
        conversations: ConversationService,
        extractor: SlotExtractionService,
        intents: IntentService,
        availability: AvailabilityService,
        retrieval: RetrievalService,
        prompts: PromptBuilder,
        gemini: GeminiService,
        currency_symbol: str,
    ):
        self._conversations = conversations
        self._extractor = extractor
        self._intents = intents
        self._availability = availability
        self._retrieval = retrieval
        self._prompts = prompts
        self._gemini = gemini
        self._currency = currency_symbol

    def handle(self, conversation_id: UUID, message: str) -> ChatResponse:
        started = time.perf_counter()
        self._conversations.require_exists(conversation_id)

        current = self._conversations.get_slots(conversation_id)
        extracted = self._extractor.extract(message, current)
        intent = self._intents.detect(message, extracted, current)

        if intent == "availability":
            response = self._availability_flow(conversation_id, extracted, current)
        else:
            response = self._knowledge_flow(conversation_id, message)

        self._conversations.add_message(conversation_id, "user", message)
        self._conversations.add_message(
            conversation_id, "assistant", history_text(response, self._currency)
        )

        logger.info(
            "Chat turn: conversation=%s intent=%s response=%s %dms",
            conversation_id,
            intent,
            response.response_type,
            round((time.perf_counter() - started) * 1000),
        )
        return response

    # --- availability ------------------------------------------------------------------------

    def _availability_flow(
        self, conversation_id: UUID, extracted: Slots, current: Slots
    ) -> ChatResponse:
        slots = self._conversations.update_slots(conversation_id, extracted, current)

        if slots.missing_fields:
            return SlotCollectionChatResponse(
                message=slot_collection_message(slots),
                missing_fields=slots.missing_fields,
                slots=slots,
            )

        try:
            result = self._availability.check(slots.check_in, slots.check_out, slots.guest_count)
        except InvalidAvailabilityRequest as exc:
            if exc.field is None:
                raise
            # Drop the offending value so the saved state matches what we are asking for.
            slots = self._conversations.clear_slot(conversation_id, slots, exc.field)
            return SlotCollectionChatResponse(
                message=invalid_slot_message(exc.message, exc.field),
                missing_fields=[exc.field],
                slots=slots,
            )

        return AvailabilityChatResponse(
            message=availability_message(result),
            check_in=result.check_in,
            check_out=result.check_out,
            guest_count=result.guest_count,
            nights=result.nights,
            rooms=result.rooms,
        )

    # --- hotel questions ---------------------------------------------------------------------

    def _knowledge_flow(self, conversation_id: UUID, message: str) -> ChatResponse:
        history = self._conversations.history(conversation_id)  # before this turn is saved
        context = self._retrieval.retrieve(message)
        prompt = self._prompts.build(context, history, message)
        return TextChatResponse(message=self._gemini.generate(prompt))


@lru_cache
def get_chat_service() -> ChatService:
    return ChatService(
        get_conversation_service(),
        get_slot_extraction_service(),
        get_intent_service(),
        get_availability_service(),
        get_retrieval_service(),
        get_prompt_builder(),
        get_gemini_service(),
        get_settings().currency_symbol,
    )
