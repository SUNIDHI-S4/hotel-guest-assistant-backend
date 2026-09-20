import re
from functools import lru_cache
from typing import Literal

from app.models.slots import Slots
from app.services.retrieval_service import mentions_facility_or_policy

Intent = Literal["availability", "knowledge"]

# Words that make a message a room search.
_AVAILABILITY_WORDS = re.compile(
    r"\b(?:availab\w*|vacanc\w*|vacant|book(?:ing|ings|ed|s)?|reserv\w*|free\s+rooms?"
    r"|rooms?\s+(?:free|open|left)|sold\s+out|fully\s+booked)\b",
    re.I,
)
# Words that say the guest means a room stay (as opposed to a spa slot, a table, ...).
_ROOM_WORDS = re.compile(r"\b(?:rooms?|suites?|stay\w*|nights?|accommodat\w*|vacanc\w*|vacant)\b", re.I)
_STAY_WORDS = re.compile(r"\b(?:rooms?|suites?|stay\w*|nights?|book\w*|reserv\w*|availab\w*)\b", re.I)
# "Can I cancel my booking?" mentions booking but is a policy question.
_NOT_A_SEARCH = re.compile(r"\b(?:cancel\w*|refund\w*|polic\w*)\b", re.I)
# Questions about how the hotel works rather than about a stay, even if they name a day.
_INFO_QUESTION = re.compile(r"\b(?:what\s+time|when|where|open|opens|opening|close|closes|closing|hours|serve\w*)\b", re.I)
# A party size in one of these is a question about a room type, not a change to the search.
_ROOM_QUESTION_CUES = re.compile(
    r"\b(?:suitable|fits?|accommodat\w*|sleeps?|capacity|prices?|costs?|how\s+much|includ\w*|allowed|polic\w*)\b",
    re.I,
)


def _is_info_question(message: str) -> bool:
    return mentions_facility_or_policy(message) or bool(_INFO_QUESTION.search(message))


class IntentService:
    """Decides whether a message is a room-availability request or a question about the hotel.

    Plain rules rather than a model call: it is instant, free, and behaves the same every
    time. It sees what the message contained (`extracted`) and what the conversation already
    knows (`current`), because a bare "Oct 21" or "3 guests" only makes sense as an answer to
    the assistant's own availability question.
    """

    def detect(self, message: str, extracted: Slots, current: Slots) -> Intent:
        if extracted.check_in or extracted.check_out:
            # A date is usually a search, but "is the pool open today?" only mentions a day.
            if _STAY_WORDS.search(message) or not _is_info_question(message):
                return "availability"
            return "knowledge"

        if (
            _AVAILABILITY_WORDS.search(message)
            and not _NOT_A_SEARCH.search(message)
            and (_ROOM_WORDS.search(message) or not _is_info_question(message))
        ):
            return "availability"

        has_saved_slots = bool(
            current.check_in or current.check_out or current.guest_count is not None
        )
        if (
            extracted.guest_count is not None
            and has_saved_slots
            and not _ROOM_QUESTION_CUES.search(message)
            and not _is_info_question(message)
        ):
            return "availability"  # "3", "what about 4 guests?" while a search is under way

        return "knowledge"


@lru_cache
def get_intent_service() -> IntentService:
    return IntentService()
