"""Fixed wording for the availability flow.

Availability answers come from the deterministic engine, so their text is templated instead
of generated: instant, free of Gemini's rate limit, and always consistent with the data shown.
"""

from datetime import date

from app.models.availability import AvailabilityResult
from app.models.chat import AvailabilityChatResponse, ChatResponse
from app.models.slots import Slots
from app.services.context_builder import format_price

_SLOT_LABELS = {
    "check_in": "check-in date",
    "check_out": "check-out date",
    "guest_count": "number of guests",
}
_ASK_AGAIN = {
    "check_in": "Please tell me a new check-in date.",
    "check_out": "Please tell me a new check-out date.",
    "guest_count": "How many guests will be staying?",
}


def format_date(value: date) -> str:
    return f"{value.day} {value:%b} {value.year}"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def slot_collection_message(slots: Slots) -> str:
    """Say what was understood so far and ask for what is still missing."""
    ask = f"Please tell me your {_join([_SLOT_LABELS[f] for f in slots.missing_fields])}."

    known = []
    if slots.check_in:
        known.append(f"check-in on {format_date(slots.check_in)}")
    if slots.check_out:
        known.append(f"check-out on {format_date(slots.check_out)}")
    if slots.guest_count is not None:
        known.append(_plural(slots.guest_count, "guest"))

    if not known:
        return f"I'd be happy to check availability. {ask}"
    return f"Thanks! So far I have {_join(known)}. {ask}"


def invalid_slot_message(problem: str, field: str) -> str:
    """`problem` explains what was wrong (it is safe to show); then ask for that slot again."""
    return f"{problem} {_ASK_AGAIN[field]}"


def availability_message(result: AvailabilityResult) -> str:
    guests = _plural(result.guest_count, "guest")
    stay = f"{format_date(result.check_in)} to {format_date(result.check_out)}"

    if result.rooms:
        nights = _plural(result.nights, "night")
        return f"Good news! These rooms are available for {guests} from {stay} ({nights}):"
    if result.party_too_large:
        return (
            f"I'm sorry, none of our rooms can accommodate {guests} in a single room. "
            "Please contact the hotel directly to arrange more than one room."
        )
    return (
        f"I'm sorry, we have no rooms available for {guests} from {stay}. "
        "Would you like to try different dates?"
    )


def history_text(response: ChatResponse, currency_symbol: str) -> str:
    """What gets stored for an assistant reply.

    Stored history has no room cards, so an availability answer keeps a plain-text list of
    the rooms; that way a reloaded chat (and the model's memory of it) still shows the options.
    """
    if isinstance(response, AvailabilityChatResponse) and response.rooms:
        lines = [
            f"- {room.name}: {format_price(room.price_per_night, currency_symbol)} per night, "
            f"{format_price(room.total_price, currency_symbol)} total"
            for room in response.rooms
        ]
        return response.message + "\n" + "\n".join(lines)
    return response.message
